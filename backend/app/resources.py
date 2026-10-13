from pathlib import Path


def resource_path(name):
    packaged = Path(__file__).parent / "_resources" / name
    return packaged if packaged.exists() else Path(__file__).parent.parent / name
