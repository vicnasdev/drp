from halo import Halo

def spin(func: object, text: str):
    def res(*args):
        with Halo(text=text+"\n"):
            func(*args)
    return res