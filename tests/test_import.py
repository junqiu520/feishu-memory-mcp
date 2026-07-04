def test_package_imports():
    import mcp_memory
    assert mcp_memory is not None


def test_package_version():
    from mcp_memory import __version__
    assert __version__ is not None
