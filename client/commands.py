import time

def run_menu_commands(client):
    """Simple text menu so the user can use CENRS from the terminal."""
    while True:
        print("\n1) Register  2) Deregister  3) Subscribe  4) Unsubscribe  5) List subscriptions  q) Quit")
        choice = input("> ").strip().lower()

        # TODO: Patricia: Implement register/deregister functions
        if choice == "1":
            pass
        elif choice == "2":
            pass
        elif choice == "3":
            location = input("Location: ")
            category = input("Category: ")
            client.subscribe(location, category)
        elif choice == "4":
            location = input("Location: ")
            category = input("Category: ")
            client.unsubscribe(location, category)
        elif choice == "5":
            client.list_subscriptions()
        elif choice == "q":
            break
        else:
            print("Unknown option.")

        time.sleep(0.3)
