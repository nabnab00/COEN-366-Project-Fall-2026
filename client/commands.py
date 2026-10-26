import time

def run_menu_commands(client):
    """Simple text menu so the user can use CENRS from the terminal."""
    while True:
        print("\n1) Register  2) Deregister  3) Subscribe  4) Unsubscribe  5) List subscriptions  q) Quit")
        choice = input("> ").strip().lower()

        # TODO: Patricia: Implement register/deregister functions
        if choice == "1":
            name = input("Name: ")
            role = input("Role (SUBSCRIBER/PUBLISHER/BOTH): ")
            tcp_port = int(input("TCP Port (0 for subscriber): "))
            client.register(name, role, tcp_port)
        elif choice == "2":
            client.deregister()
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
