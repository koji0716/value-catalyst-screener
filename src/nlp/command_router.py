def route_natural_language(text):
    """Map a few Japanese analysis prompts to CLI command suggestions."""
    prompt = (text or "").lower()
    if "カタリスト" in prompt and ("割安" in prompt or "探" in prompt):
        return [
            "python cli.py sync --market jp",
            "python cli.py screen --preset catalyst_value",
            "python cli.py report --preset catalyst_value --format html",
        ]
    if "7203" in prompt or "トヨタ" in prompt:
        return ["python cli.py explain --ticker 7203"]
    if "売られすぎ" in prompt or "反発" in prompt:
        return ["python cli.py screen --preset rebound_value"]
    if "per" in prompt and "pbr" in prompt:
        return ["python cli.py screen --market jp --max-per 15 --max-pbr 1.0 --min-equity-ratio 30"]
    return ["python cli.py screen --preset balanced"]

