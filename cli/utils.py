from halo import Halo

def spin(func: object, text: str):
    def res(*args):
        with Halo(text=text) as spinner:
            func(*args)
            spinner.stop()
    return res