from typing import Any


def profile_tabular(file_path: str) -> dict[str, Any]:
    """Backward-compatible entry point for reusable tabular profiling."""
    try:
        from app.services.profiling_service import profile_tabular_file

        return profile_tabular_file(file_path)
    except Exception as exc:
        return {"error": f"Failed to read or profile file: {exc}"}
