from rich.console import Console
from time import sleep

console = Console()

def spin(func: object, text: str):
    def res(*args):
        with console.status(text):
            sleep(0.1)
            console.print()
            func(*args)
    return res