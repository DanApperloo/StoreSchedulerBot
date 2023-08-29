from importlib import resources


def get_resource_path(resource: str) -> str:
    with resources.path("test.resource", resource) as resource_file:
        return str(resource_file)
