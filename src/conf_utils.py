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
    if "llm" not in configuration:
        errors.append("Missing 'llm' section in configuration")
    else:
        llm = configuration["llm"]
        if not llm.get("model_id"):
            errors.append("llm.model_id is required")
        temp = llm.get("temperature")
        if temp is None or not (0 <= temp <= 1):
            errors.append("llm.temperature must be between 0 and 1")
        max_tok = llm.get("max_tokens")
        if not isinstance(max_tok, int) or max_tok <= 0:
            errors.append("llm.max_tokens must be a positive integer")
    if "report" not in configuration:
        errors.append("Missing 'report' section in configuration")
    else:
        rpt = configuration["report"]
        chunk = rpt.get("chunk_size")
        if not isinstance(chunk, int) or chunk <= 0:
            errors.append("report.chunk_size must be a positive integer")

        incr = rpt.get("incremental")
        workers = rpt.get("max_workers")
        if incr is True and workers != 1:
            errors.append("For incremental mode, report.max_workers must be 1")
        if incr is False and (not isinstance(workers, int) or workers < 1):
            errors.append("report.max_workers must be >=1")
    return errors
