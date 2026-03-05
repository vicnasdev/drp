"""login — Authenticate"""

from . import Arg, Command, register
from cli.config import set as set_config
from cli.defaults import server

cmd = register(Command(
    name="login",
    description="Authenticate.",
    args=(
        Arg("--server", "drp server", required=True, default=server),
        Arg("--token", "Authentication token"),
        Arg("username", "Username or email"),
        Arg("password", "Password"),
        Arg("--duration", "Duration of the session"),
    )
))

def run(args: dict[str, str]):
    # POST /api/v1/auth/login with {username, password, duration} or {token}
    # store returned token with keyring.set_password("drp", "token", token)
    # store server with set_config("server", server)
    # store machine_info() alongside token so dashboard can show device name
    
    set_config("server", args["server"])
    pass

cmd.run = run