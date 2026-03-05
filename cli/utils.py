from rich.console import Console

console = Console()

def spin(func: object, text: str):
    def res(*args):
        with console.status(text):
            func(*args)
    return res