# Package init
def __getattr__(name):
    try:
        import webgis.backend.config as backend_config
        return getattr(backend_config, name)
    except (ImportError, AttributeError):
        raise AttributeError(f"module 'config' has no attribute '{name}'")

