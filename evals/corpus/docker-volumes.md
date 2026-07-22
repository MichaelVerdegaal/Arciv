# Docker storage and volumes

## Bind mounts vs named volumes

Bind mounts map a host directory into the container and are ideal for source
code during development. Named volumes are managed by Docker under
/var/lib/docker/volumes and survive container removal; prefer them for
databases because ownership and SELinux labels are handled for you.

## Snapshotting a data volume

To capture the Postgres data directory, stop writes and run a throwaway
container that tars the volume:

```bash
docker run --rm -v pgdata:/data -v "$PWD":/out alpine \
  tar czf /out/pgdata-$(date +%F).tgz -C /data .
```

Restoring is the same trick with `tar xzf` pointed at the empty volume.

## Cleaning up

`docker volume ls -f dangling=true` lists volumes no container references.
`docker system df -v` shows which ones are actually large before you prune.
