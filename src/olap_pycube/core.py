# %% Setting up

import os
import sys
from pathlib import Path

import clr
import pandas as pd
from dotenv import load_dotenv


class AdomdConnection:
    x = 1
    # Only defined here to  avoid warnings from Python linters
    # as the AdomdConnection class can only be imported after
    # a DLL file has been loaded from the pytabular package


# %% Function to find the local DLL needed to connect to the cube


def find_dll_path() -> Path:
    """
    Finds the correct path to the AdomdClient DLL that is
    necessary to load before attempting a connection to the cube,
    then loads the DLL into memory. Supports both global and local
    Python environments.
    """

    # Finding the executable and specifying DLL to look for
    executable_path = Path(sys.executable)
    env_path = executable_path.parent.parent
    dll_path = env_path.joinpath(
        r"Lib/site-packages/pytabular/dll/Microsoft.AnalysisServices.AdomdClient.dll"
    )

    # Raising an error if the DLL file does not exist (this means
    # the pytabular package is not installed)
    if not dll_path.exists():
        raise FileExistsError(
            f"DLL not found at: {dll_path}. Please double-check and ensure the 'python-tabular' package is installed in your Python environment."  # noqa
        )

    return dll_path


# %% Function to connect to the cube and query (meta)data


def connect_to_cube(env_conn_name: str) -> AdomdConnection:
    """
    Establishes a connection to a given cube based on a
    connection string provided in a .ENV file. Returns the
    connection so that it can be used in other functions for
    e.g. querying data or metadata from the cube.
    """

    # Importing the DLL if found
    dll_path = find_dll_path()
    clr.AddReference(str(dll_path))

    # Note: the import below can only take place after loading the
    # special DLL from the "python-tabular" package
    from Microsoft.AnalysisServices.AdomdClient import AdomdConnection  # type: ignore

    # Get the connection string from the .ENV variables
    load_dotenv()
    CONN_STRING = os.getenv(env_conn_name)
    if not CONN_STRING:
        raise ValueError(
            f"Connection string '{env_conn_name}' not found in environment variables. Please check your .env file."
        )

    conn = AdomdConnection(CONN_STRING)
    conn.Open()

    return conn


def get_cube_datasets(conn: AdomdConnection) -> list:

    # Get names of the databases in the connection
    schema = conn.GetSchemaDataSet("DBSCHEMA_CATALOGS", None)

    datasets = []

    for row in schema.Tables[0].Rows:
        datasets.append(row[0])

    return datasets


def get_cube_names(conn: AdomdConnection) -> dict:

    # Get names of the cubes in the database
    cubes = conn.GetSchemaDataSet("MDSCHEMA_CUBES", None)

    out = {}

    for row in cubes.Tables[0].Rows:
        out.update({row["CUBE_NAME"]: row["CUBE_TYPE"]})

    return out


def get_cube_measures(conn: AdomdConnection) -> pd.DataFrame:

    # Get names of the measures in the cube
    measures = conn.GetSchemaDataSet("MDSCHEMA_MEASURES", None)

    m_names = []
    m_captions = []
    m_uniques = []
    m_groups = []
    m_displays = []
    m_expressions = []

    for row in measures.Tables[0].Rows:
        m_names.append(row["MEASURE_NAME"])
        m_captions.append(row["MEASURE_CAPTION"])
        m_uniques.append(row["MEASURE_UNIQUE_NAME"])
        m_groups.append(row["MEASUREGROUP_NAME"])
        m_displays.append(row["MEASURE_DISPLAY_FOLDER"])
        m_expressions.append(row["EXPRESSION"])

    out = {
        "measure_name": m_names,
        "measure_caption": m_captions,
        "measure_unique_name": m_uniques,
        "measure_group_name": m_groups,
        "measure_display_folder": m_displays,
        "expression": m_expressions,
    }
    out = pd.DataFrame(out)

    return out


def get_cube_hierarchies(conn: AdomdConnection) -> pd.DataFrame:

    # Get hierarchies
    hierarchies = conn.GetSchemaDataSet("MDSCHEMA_HIERARCHIES", None)

    h_dimensions = []
    h_hierarchies = []
    h_captions = []

    for row in hierarchies.Tables[0].Rows:
        h_dimensions.append(row["DIMENSION_UNIQUE_NAME"])
        h_hierarchies.append(row["HIERARCHY_UNIQUE_NAME"])
        h_captions.append(row["HIERARCHY_CAPTION"])

    out = {
        "dimension_unique_name": h_dimensions,
        "hierarchy_unique_name": h_hierarchies,
        "hierarchy_caption": h_captions,
    }
    out = pd.DataFrame(out)

    return out


def query_cube_data(conn: AdomdConnection, query: str) -> pd.DataFrame:
    """Base function to execute MDX and return a DataFrame."""
    cmd = conn.CreateCommand()
    cmd.CommandText = query

    reader = cmd.ExecuteReader()

    data = []
    column_names = [reader.GetName(i) for i in range(reader.FieldCount)]

    while reader.Read():
        row = [reader.GetValue(i) for i in range(reader.FieldCount)]
        data.append(row)

    reader.Close()

    # Handle case where result is empty to avoid DataFrame creation errors
    if not data:
        return pd.DataFrame(columns=column_names)

    return pd.DataFrame(data, columns=column_names)


def load_data_from_cube(
    env_conn_name: str,
    cube_name: str,
    measures: list,
    rows: list | None = None,
    columns: list | None = None,
    non_empty: bool = True,
    print_mdx_query: bool = False,
):
    if isinstance(measures, str):
        measures = [measures]

    def format_measure(m):
        m = m.strip()

        if m.startswith("[Measures]."):
            return m

        if m.startswith("["):
            return f"[Measures].{m}"

        return f"[Measures].[{m}]"

    def format_set(item):
        item = item.strip()

        if (
            ".MEMBERS" in item
            or ".Children" in item
            or "{" in item
            or "*" in item
            or "FILTER(" in item.upper()
        ):
            return item

        return f"{item}.MEMBERS"

    def crossjoin(items):
        if not items:
            return None

        formatted = [format_set(x) for x in items]

        if len(formatted) == 1:
            return formatted[0]

        return " * ".join(formatted)

    measures_md = "{ " + ", ".join(format_measure(m) for m in measures) + " }"

    column_set = crossjoin(columns)
    row_set = crossjoin(rows)

    # Measures × column dimensions
    if column_set:
        columns_md = f"{measures_md} * {column_set}"
    else:
        columns_md = measures_md

    if non_empty:
        columns_md = f"NON EMPTY {columns_md}"

    query = f"SELECT {columns_md} ON COLUMNS"

    if row_set:
        if non_empty:
            row_set = f"NON EMPTY {row_set}"

        query += f", {row_set} ON ROWS"

    query += f" FROM {cube_name}"

    conn = connect_to_cube(env_conn_name)

    # Optional printing of the MDX query, if so specified by the user
    if print_mdx_query:
        print(query)

    return query_cube_data(conn, query)


# %%
