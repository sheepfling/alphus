def copy_file(source, destination):
    """A name-based native call-order check can review this call."""
    return source, destination


source_path = "input.txt"
destination_path = "output.txt"
copy_file(destination_path, source_path)
