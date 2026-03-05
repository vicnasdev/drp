from rich.console import Console

def spin(func: object, text: str):
    def res(*args):
        with Console.status(text):
            func(*args)
    return res