import os
import sys
import subprocess
import time

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_header():
    print("==========================================")
    print("       LYRN SERVER STARTUP WIZARD")
    print("==========================================")
    print()

def install_dependencies():
    print("\n--- Installing Dependencies ---")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "dependencies/requirements.txt"])
        print("Dependencies installed successfully.")
    except Exception as e:
        print(f"Error installing dependencies: {e}")
    input("Press Enter to continue...")

def install_tailscale():
    print("\n--- Installing Tailscale ---")
    print("Attempting to install Tailscale using the official install script.")
    print("This may require sudo access (password prompt).")

    try:
        # Using the official install script is safer than manually adding keys/repos
        # especially given the potentially malformed URLs in the prompt.
        cmd = "curl -fsSL https://tailscale.com/install.sh | sh"
        subprocess.check_call(cmd, shell=True)
        print("\nTailscale installation script completed.")
        print("You may need to run 'sudo tailscale up' to connect.")
    except Exception as e:
        print(f"Error installing Tailscale: {e}")
        print("Please refer to https://tailscale.com/download for manual instructions.")
    input("Press Enter to continue...")

def setup_token():
    print("\n--- Admin Token Setup ---")
    if os.path.exists("admin_token.txt"):
        print("admin_token.txt already exists.")
        choice = input("Generate new token? (Y/N): ").strip().upper()
        if choice != 'Y':
            return

    try:
        subprocess.check_call([sys.executable, "token_generator.py"])
        # token_generator.py usually prints the token.
    except Exception as e:
        print(f"Error generating token: {e}")
    input("Press Enter to continue...")

def setup_port():
    print("\n--- Port Setup ---")
    current_port = "8000"
    if os.path.exists("port.txt"):
        try:
            with open("port.txt", "r") as f:
                current_port = f.read().strip()
        except: pass

    print(f"Current Port: {current_port}")
    choice = input("Change port? (Y/N): ").strip().upper()
    if choice == 'Y':
        new_port = input("Enter new port: ").strip()
        if new_port.isdigit():
            with open("port.txt", "w") as f:
                f.write(new_port)
            print("Port updated.")
        else:
            print("Invalid port.")
            input("Press Enter to continue...")

def main():
    while True:
        clear_screen()
        print_header()
        print("1. Install Dependencies")
        print("2. Install Tailscale")
        print("3. Setup Admin Token")
        print("4. Setup Port")
        print("5. Start LYRN Server")
        print("Q. Quit")
        print()

        choice = input("Select an option: ").strip().upper()

        if choice == '1':
            install_dependencies()
        elif choice == '2':
            install_tailscale()
        elif choice == '3':
            setup_token()
        elif choice == '4':
            setup_port()
        elif choice == '5':
            # Start Server
            print("\nStarting Server...")
            try:
                subprocess.call([sys.executable, "start_lyrn.py"])
            except KeyboardInterrupt:
                pass
            input("Server stopped. Press Enter...")
        elif choice == 'Q':
            break

if __name__ == "__main__":
    main()
