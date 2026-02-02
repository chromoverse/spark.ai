from app.client_core.utils.app_searcher import AppSearcher

def find_app(app_name: str) :
    """
    Find the full path of an application by its name.
    """
    searcher = AppSearcher()
    return searcher.find_app(app_name)


if __name__ == "__main__":
    print(find_app("photos"))  # Example usage  