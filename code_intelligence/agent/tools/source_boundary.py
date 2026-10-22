"""Input validation for bounded, line-scoped source reads."""


def validate_source_range(line_start, line_end, max_lines=200):
    values = (line_start, line_end, max_lines)
    if any(type(value) is not int for value in values):
        return 'Error: line bounds and maximum must be integers.'
    if line_start < 1 or line_end < line_start:
        return 'Error: source line range is invalid.'
    if max_lines < 1 or line_end - line_start + 1 > max_lines:
        return 'Error: source line range exceeds the maximum allowed size.'
    return None
