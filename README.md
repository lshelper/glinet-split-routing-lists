# GL.iNet Split Routing Lists

Public domain lists for GL.iNet VPN policy routing and DNS-based split routing.

The main list contains domains that should be opened through a Russia-routed IP address or VPN endpoint.

## GL.iNet URLs

Use these raw URLs in GL.iNet VPN policy rules:

```text
https://raw.githubusercontent.com/lshelper/glinet-split-routing-lists/main/lists/glinet/ru.txt
https://raw.githubusercontent.com/lshelper/glinet-split-routing-lists/main/lists/glinet/direct.txt
```

Optional compact version:

```text
https://raw.githubusercontent.com/lshelper/glinet-split-routing-lists/main/lists/glinet/ru.compact.txt
```

## Lists

- `lists/glinet/ru.txt` - full public list of domains to route through the Russia endpoint.
- `lists/glinet/ru.compact.txt` - compact version that removes child domains already covered by parent domains in the source list.
- `lists/glinet/direct.txt` - explicit direct-route exclusions. Currently empty.
- `lists/dnsmasq/ru.ipset.conf` - dnsmasq/ipset-style output for advanced OpenWrt setups.
- `lists/meta/manifest.json` - generated list statistics.
- `lists/meta/checksums.txt` - SHA-256 checksums for generated outputs.

## GL.iNet Setup

In GL.iNet firmware v4.7+:

1. Open `VPN Dashboard`.
2. Select the Russia-routed VPN tunnel.
3. Set policy mode to route only the specified destination list.
4. Import `lists/glinet/ru.txt` by raw URL.
5. Use `lists/glinet/direct.txt` as an exclusion list if needed.

Clients should use the router for DNS. Browser DoH, Android Private DNS, or another DNS path outside the router can prevent domain-based routing from matching correctly.

## Updating

Edit source files, then rebuild generated outputs:

```bash
python3 scripts/build.py
python3 scripts/validate.py
python3 scripts/build.py --check
python3 -m unittest discover -s tests
```

Source files live in `sources/`:

- `sources/ru.raw.txt`
- `sources/direct.raw.txt`

Private router-local entries should go into `sources/private.local.txt`, which is ignored by git.

## Validation Rules

The build rejects:

- URLs with schemes or paths
- wildcard domains
- invalid domain labels
- IPv6 entries
- private IPv4 addresses and private CIDR ranges in public lists

The generated GL.iNet files are plain text: one domain, IPv4 address, or CIDR range per line.

## License

MIT
