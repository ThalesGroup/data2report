from typing import Optional, List


def validate_configuration(configuration: dict, report_id: Optional[str]) -> List[str]:
    errors = []
    if "id" not in configuration or not configuration["id"]:
        errors.append("Missing report id")
    elif report_id and configuration["id"] != report_id:
        errors.append(
            "Report id in configuration does not match the provided report_id"
        )
    # TODO: add more validations
    # for example max_workers for incremental report must be 1, chunk_size, etc.
    return errors
