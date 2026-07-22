# Personal backup strategy

## The 3-2-1 rule

Three copies of anything that matters, on two different media, one of them
offsite. The laptop counts as copy one, the external SSD as copy two, and
the encrypted cloud bucket as the offsite third. RAID is availability, not
backup — it happily mirrors your mistakes.

## Restic routine

Nightly `restic backup` of the home directory to the local drive, weekly to
the bucket. Prune with `--keep-daily 7 --keep-weekly 5 --keep-monthly 12`.
The repository password lives in the password manager, printed once and
stored with the passports.

## Test the restores

A backup that has never been restored is a hope, not a plan. Quarterly:
pick three random files and one full directory, restore them to /tmp, and
diff against the originals.
