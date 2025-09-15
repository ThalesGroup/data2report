import os


def split_input_file(chunk_folder: str, input_file: str, chunk_size: int) -> (int, int):
    """
        Splits the input file into chunks and stores them in the specified chunk folder.
    ´
        Args:
            chunk_folder (str): Path to the folder where chunks will be stored.
            input_file (str): Path to the input file to split. Can be a text file or a gzipped (.gz) file.
            chunk_size (int): Number of records per chunk.

        Returns:
            tuple: (chunks, records)
                - chunks (int): Number of chunks created or found.
                - records (int): Number of records processed, or None if chunks already exist.
    """
    if not os.path.exists(chunk_folder):
        os.makedirs(chunk_folder)
        chunks = 0
    else:
        chunks = len(os.listdir(chunk_folder))
    if chunks > 0:
        return chunks, None
    records = 0
    with open(input_file, "r") as f:
        for _ in f:
            if records % chunk_size == 0:
                chunks += 1
                # TODO write chunk (gz file). If s3 path, upload to s3
                # TODO used the csv_file_with_1k_lines fixture for testing
            records += 1
    return chunks, records
