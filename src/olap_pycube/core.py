# %% Setting up

import os
import re
import sys
from pathlib import Path

import clr
import numpy as np
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

    Args:
        env_conn_name (str): name of the .ENV variable that
        contains the connection string for accessing the cube

    Raises:
        ValueError: if the given variable is not found in the
        .ENV file, produce an error

    Returns:
        AdomdConnection: connection to the cube that can be
        used to query data and metadata alike
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


def get_catalog_name(conn: AdomdConnection) -> str:
    """
    Finds the name of the catalog to source data from based
    on an AdomdConnection established via .ENV connection string.

    Args:
        conn (AdomdConnection): an alredy established
        connection to the cube used for querying (meta)data

    Returns:
        str: name of the catalog associated with the connection
        string in the .ENV var used to create the AdomdConnection
    """

    parts = conn.ConnectionString.split("; ")

    catalogue_name = None

    for part in parts:
        # Strip whitespace just in case and check for the key
        if part.strip().startswith("Initial Catalog="):
            # Split by '=' and take the second part (the value)
            catalogue_name = part.split("=", 1)[1]
            break

    # Note that [] brackets are needed for irregular spellings
    return f"[{catalogue_name}]"


def get_cube_datasets(conn: AdomdConnection) -> list:
    """
    Fetches a list of all datasets available in the cube.

    Args:
        conn (AdomdConnection): an alredy established
        connection to the cube used for querying (meta)data

    Returns:
        list: list of available datasets in the cube
    """

    # Get names of the databases in the connection
    schema = conn.GetSchemaDataSet("DBSCHEMA_CATALOGS", None)

    datasets = []

    for row in schema.Tables[0].Rows:
        datasets.append(row[0])

    return datasets


def get_cube_names(conn: AdomdConnection) -> dict:
    """
    Fetches a dictionary wwith the cube name and type.
    This can be useful to know when constructing manual
    cube data queries.

    Args:
        conn (AdomdConnection): an alredy established
        connection to the cube used for querying (meta)data

    Returns:
        dict: list of available cubes and cube types
    """

    # Get names of the cubes in the database
    cubes = conn.GetSchemaDataSet("MDSCHEMA_CUBES", None)

    out = {}

    for row in cubes.Tables[0].Rows:
        out.update({row["CUBE_NAME"]: row["CUBE_TYPE"]})

    return out


def get_cube_measures(conn: AdomdConnection) -> pd.DataFrame:
    """
    Gets metadata on all available measures in a given cube
    defined based on the AdomdConnection connection. This
    includes measurure name and unique name, caption, group,
    display folder (as seen in MS Excel) and expression (if
    available).

    Args:
        conn (AdomdConnection): an alredy established
        connection to the cube used for querying (meta)data

    Returns:
        pd.DataFrame: df with measure-related metadata
    """

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


def get_cube_dimensions(conn: AdomdConnection) -> pd.DataFrame:
    """
    Gets metadata on all available dimensions, hierarchies, and
    levels in a given cube.

    Args:
        conn (AdomdConnection): an already established connection
        to the cube used for querying (meta)data.

    Returns:
        pd.DataFrame: DataFrame containing dimension, hierarchy,
        and level metadata.
    """

    dimensions = conn.GetSchemaDataSet("MDSCHEMA_DIMENSIONS", None)
    hierarchies = conn.GetSchemaDataSet("MDSCHEMA_HIERARCHIES", None)
    levels = conn.GetSchemaDataSet("MDSCHEMA_LEVELS", None)

    rows = []

    # Get dimensions
    for dim in dimensions.Tables[0].Rows:
        dimension_unique_name = dim["DIMENSION_UNIQUE_NAME"]

        # Skip the special Measures dimension
        if dimension_unique_name == "[Measures]":
            continue

        # Find hierarchies belonging to this dimension
        for hierarchy in hierarchies.Tables[0].Rows:
            if hierarchy["DIMENSION_UNIQUE_NAME"] != dimension_unique_name:
                continue

            hierarchy_unique_name = hierarchy["HIERARCHY_UNIQUE_NAME"]

            # Find levels belonging to this hierarchy
            for level in levels.Tables[0].Rows:
                if level["DIMENSION_UNIQUE_NAME"] != dimension_unique_name:
                    continue

                if level["HIERARCHY_UNIQUE_NAME"] != hierarchy_unique_name:
                    continue

                rows.append(
                    {
                        "dimension_name": dim["DIMENSION_NAME"],
                        "dimension_caption": dim["DIMENSION_CAPTION"],
                        "dimension_unique_name": dimension_unique_name,
                        "hierarchy_name": hierarchy["HIERARCHY_NAME"],
                        "hierarchy_caption": hierarchy["HIERARCHY_CAPTION"],
                        "hierarchy_unique_name": hierarchy_unique_name,
                        "level_name": level["LEVEL_NAME"],
                        "level_caption": level["LEVEL_CAPTION"],
                        "level_unique_name": level["LEVEL_UNIQUE_NAME"],
                        "level_number": level["LEVEL_NUMBER"],
                    }
                )

    return pd.DataFrame(rows)


def get_cube_hierarchies(conn: AdomdConnection) -> pd.DataFrame:
    """
    Gets metadata on hierarchies defined in the cube.

    Args:
        conn (AdomdConnection): an alredy established
        connection to the cube used for querying (meta)data


    Returns:
        pd.DataFrame: df with hierarchy metadata
    """

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
    """
    Queries the given cube using custom MDX code. Returns
    the data fetched as a pandas data frame. Please make sure
    that names of measures and dimensions are enclosed within
    square brackets in order to avoid data retrieval errors.
    Write e.g. "[Measure 1]" instead of "Measure 1".

    Args:
        conn (AdomdConnection): an alredy established
        connection to the cube used for querying (meta)data
        query (str): MDX query

    Returns:
        pd.DataFrame: df with data fetched from the cube
    """

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


# %% Functions to actually download data from the cube


def load_data_from_cube(
    env_conn_name: str,
    measures: list,
    rows: list | None = None,
    columns: list | None = None,
    non_empty: bool = True,
    print_mdx_query: bool = False,
    pythonize_col_names: bool = False,
) -> pd.DataFrame:
    """
    Automatically connects to a given cube, constructs an MDX
    query to fetch the specified fields and measures from the
    cube, then loads the data. Optionally prints the auto-
    generated MDX query and performs cleaning of the column
    names of the resulting df so that they match Python
    naming convetions.

    Args:
        env_conn_name (str): name of the .ENV variable that
        contains the connection string for accessing the cube
        measures (list): _description_
        rows (list | None, optional): _description_. Defaults to None.
        columns (list | None, optional): _description_. Defaults to None.
        non_empty (bool, optional): _description_. Defaults to True.
        print_mdx_query (bool, optional): _description_. Defaults to False.
        pythonize_col_names (bool, optional): _description_. Defaults to False.

    Returns:
        pd.DataFrame: _description_
    """

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

    # Connecting to the cube & finding the initial catalog name
    conn = connect_to_cube(env_conn_name)
    catalog_name = get_catalog_name(conn)
    query += f" FROM {catalog_name}"

    # Optional printing of the MDX query, if so specified by the user
    if print_mdx_query:
        print(query)

    # Loading the data
    df = query_cube_data(conn, query)

    # Optional renaming of the columns so they conform to
    # common Python standards (e.g. no spaces/weird characters)
    if pythonize_col_names:
        df = pythonize_columns(df)

    return df


# %% Other helper functions


def clean_cube_column(name: str) -> str:
    """
    Takes a messy column name from a cube and transforms it
    to a cleaner, Python-comptabile version. This includes
    removal of whitespaces, unexpected charaters, numbers, etc.
    """

    # 0. If the col name is not a string, convert it to string
    name = str(name)

    # 1. Extract the relevant name part from the hierarchy
    # Captures content inside the last [...] block
    match = re.search(r"\[([^\]]+)\](?:\.\[MEMBER_CAPTION\])?$", name)

    if match:
        clean_name = match.group(1)
    else:
        # Fallback for simple names without hierarchy
        clean_name = name.replace("[", "").replace("]", "")

    # 2. Normalize case
    clean_name = clean_name.lower()

    # 3. Replace spaces, parentheses, and special chars with underscores
    clean_name = re.sub(r"[^\w]", "_", clean_name)

    # 4. Remove duplicate underscores
    clean_name = re.sub(r"_+", "_", clean_name)

    # 5. Strip leading/trailing underscores
    clean_name = clean_name.strip("_")

    # 6. Remove numbers ONLY if they are at the very beginning
    clean_name = re.sub(r"^\d+", "", clean_name)

    # Final cleanup in case removing numbers left a leading underscore
    return clean_name.strip("_")


def pythonize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Makes all column names in a given pandas data frame
    Python-compatible by cleaning up the strings. Ensures
    that no two columns have the same name after the clean-up.
    Can be applied directly to the entire data frame.
    """

    # Automatic clean-up of column names
    df_out = df.copy()
    new_names = [clean_cube_column(col) for col in df_out.columns]

    # Checking for any potentially repeated column names
    n_total = len(new_names)
    n_unique = len(set(new_names))
    adj_needed = n_total != n_unique

    # If names are not unique, add suffixes such as "_1", "_2"
    if adj_needed:

        # First, get all column names and of N of repeats per col
        df_names = pd.DataFrame({"auto_name": new_names})
        df_names = df_names.sort_values("auto_name").reset_index(names="original_index")
        df_names["count"] = df_names.groupby("auto_name")["original_index"].transform(
            "count"
        )
        df_names["cum_count"] = (
            df_names.groupby("auto_name")["original_index"].cumcount() + 1
        )
        df_names["final_name"] = (
            df_names["auto_name"] + "_" + df_names["cum_count"].astype(str)
        )
        df_names["final_name"] = np.where(
            df_names["count"] == 1, df_names["auto_name"], df_names["final_name"]
        )
        df_names = df_names.sort_values("original_index")
        final_names = df_names.columns.tolist()

    else:
        final_names = new_names

    df_out.columns = final_names

    return df_out


# %%
