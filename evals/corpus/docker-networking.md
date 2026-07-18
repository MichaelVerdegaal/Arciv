# Docker networking notes

## Container-to-container DNS

Containers on the same user-defined bridge network reach each other by service
name; the embedded DNS server at 127.0.0.11 resolves them. The default bridge
network does *not* provide name resolution — only IP addresses work there,
which is why `ping web` fails until you create a network with
`docker network create appnet` and attach both containers.

## Port publishing

`-p 8080:80` maps host port 8080 to container port 80. Publishing binds
0.0.0.0 by default; use `-p 127.0.0.1:8080:80` to keep a service off the LAN.
`docker port <container>` shows active mappings. Remember that published ports
bypass ufw rules because Docker writes its own iptables chains.

## Debugging connectivity

`docker network inspect appnet` lists attached containers and their addresses.
For a quick shell with network tools, run a `nicolaka/netshoot` container on
the same network and use `dig`, `curl`, or `tcpdump` from inside.
