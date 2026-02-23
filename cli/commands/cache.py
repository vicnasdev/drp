"""
drp cache — view the local drop cache.
drp rmcache — remove entries from the local drop cache.

  drp cache                   list cached drops
  drp rmcache <key>           remove a specific key from the cache
  drp rmcache --all           clear the entire cache
"""

from cli import config
from cli.api.helpers import ok, err


def cmd_cache(args):
    """List locally cached drops and collections."""
    from cli.format import cyan, blue, dim, grey, green, bold

    drops = config.load_local_drops()

    if not drops:
        print(dim('  (cache is empty)'))
        return

    print(f'  {bold("cached drops")}  {dim(f"({len(drops)} entries)")}')
    print(f'  {dim("─" * 40)}')

    for d in drops:
        key  = d.get('key', '?')
        ns   = d.get('ns', 'c')
        kind = d.get('kind', '')
        host = d.get('host', '')
        synced = d.get('from_server', False)

        key_str  = blue(f'f/{key}') if ns == 'f' else cyan(key)
        sync_tag = green('synced') if synced else grey('local')
        print(f'  {key_str:<30}  {dim(kind):<10}  {dim(sync_tag)}')

    # Also show collection slugs if any
    try:
        from cli.completion import _read_collection_cache
        slugs = _read_collection_cache('')
        if slugs:
            from cli.format import magenta
            print()
            print(f'  {bold("cached collections")}  {dim(f"({len(slugs)} slugs)")}')
            print(f'  {dim("─" * 40)}')
            for s in slugs:
                print(f'  {magenta(s)}')
    except Exception:
        pass

    print()
    cache_dir = config.CONFIG_DIR
    print(f'  {dim("cache dir:")} {cache_dir}')


def cmd_rmcache(args):
    """Remove entries from the local drop cache."""
    from cli.format import green, red, dim

    clear_all = getattr(args, 'all', False)
    key = getattr(args, 'key', None)

    if clear_all:
        config.save_local_drops([])
        # Also clear collections cache
        col_file = config.CONFIG_DIR / 'collections.json'
        if col_file.exists():
            col_file.write_text('[]')
        print(f'  {green("✓")} cache cleared')
        return

    if not key:
        print(f'  {red("✗")} Usage: drp rmcache <key>  or  drp rmcache --all')
        return

    drops = config.load_local_drops()
    before = len(drops)
    drops = [d for d in drops if d.get('key') != key]
    after = len(drops)

    if before == after:
        print(f'  {red("✗")} key "{key}" not found in cache')
        return

    config.save_local_drops(drops)
    removed = before - after
    print(f'  {green("✓")} removed {removed} entr{"y" if removed == 1 else "ies"} for "{key}"')
