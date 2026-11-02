def build_report(rows, report_path):
    if rows:
        write_table(report_path, rows)
    publish(read_table(report_path))


def process_input(input_path):
    parsed = parse_input(input_path)
    record_provenance(digest_input(input_path))
    return parsed


def process_snapshot(snapshot_bytes):
    parsed = parse_bytes(snapshot_bytes)
    record_provenance(digest_bytes(snapshot_bytes))
    return parsed
