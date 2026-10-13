from app import __name__ as package_name


def test_application_package_is_importable() -> None:
    assert package_name == "app"
