#!/bin/bash
# Startup script for the one-shot resize helper VM. Waits for kiem-sandbox to be TERMINATED,
# sets its machine type to n2-standard-96, starts it, then deletes this helper. Logs to the serial console.
Z=us-central1-f; P=delivery-g-obi; T=kiem-sandbox; NEW=n2-standard-96
log(){ echo "RESIZE-HELPER $(date -u +%FT%TZ) $*" | tee /dev/ttyS0 2>/dev/null; }
log "started on $(hostname)"
for i in $(seq 1 90); do
  s=$(gcloud compute instances describe $T --zone $Z --project $P --format='value(status)' 2>/dev/null)
  log "poll $i status=$s"
  [ "$s" = "TERMINATED" ] && break
  sleep 10
done
if [ "$s" = "TERMINATED" ]; then
  if gcloud compute instances set-machine-type $T --zone $Z --project $P --machine-type $NEW 2>&1 | tee /dev/ttyS0; then
    log "set-machine-type $NEW ok"
  else
    log "set-machine-type FAILED, starting with the old type"
  fi
  gcloud compute instances start $T --zone $Z --project $P 2>&1 | tee /dev/ttyS0
  log "start issued; final type=$(gcloud compute instances describe $T --zone $Z --project $P --format='value(machineType.basename(),status)')"
else
  log "target never reached TERMINATED after 15 min; leaving it alone"
fi
log "deleting self"
gcloud compute instances delete "$(hostname)" --zone $Z --project $P --quiet 2>&1 | tee /dev/ttyS0
