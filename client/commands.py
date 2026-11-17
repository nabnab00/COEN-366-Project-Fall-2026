import time

def run_menu_commands(client):
    """Simple text menu so the user can use CENRS from the terminal."""
    while True:
        print("\n1) Register  2) Deregister  3) Subscribe  4) Unsubscribe  5) List subscriptions 6) Publish Alert 7) Update Alert 8) Close Alert 9) Status Report  q) Quit")
        choice = input("> ").strip().lower()

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
        # TODO P2-10
        elif choice == "6":
            category = input("Category: ")
            location = input("Location: ")
            severity = input("Severity: ")
            title = input("Title: ")
            description = input("Description: ")
            attachment = input("Attachment (optional): ")
            client.publish_alert(category, location, severity, title, description, attachment)
        elif choice == "7":
            incident_id = input("Incident ID: ")
            severity = input("Severity: ")
            title = input("Title: ")
            description = input("Description: ")
            client.update_alert(incident_id, severity, title, description)
        elif choice == "8":
            incident_id = input("Incident ID: ")
            reason = input("Reason: ")
            client.close_alert(incident_id, reason)
        elif choice == "9":
            incident_id = input("Incident ID: ")
            status = input("Status: ")
            client.status_report(incident_id, status)
        elif choice == "q":
            break
        else:
            print("Unknown option.")

        time.sleep(0.3)
