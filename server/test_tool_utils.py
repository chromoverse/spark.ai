from app.agent.shared.utils.searcher.system_searcher import SystemSearcher

searcher = SystemSearcher()

def test_app_resolver():
    apps = searcher.get_all_apps()
    print(f"Found {len(apps)} apps")
    app = searcher.search_app("device manager")
    print("Search result ':", app)
    

test_app_resolver()
