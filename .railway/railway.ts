import { defineRailway, preserve, project, service } from "railway/iac";

export default defineRailway(() => {
  const auctionEtlPersistentWorker = service("auction-etl-persistent-worker", {
    replicas: { "sfo": 1 },
    env: {
      AUCTION_BUYEE_PROFILE_DIR: preserve(),
      AUCTION_ENV: preserve(),
      DATABASE_URL: preserve(),
      PYTHONUNBUFFERED: preserve(),
    },
    build: {
      builder: "DOCKERFILE",
      dockerfilePath: "Dockerfile.auction-etl.refresh",
    },
    deploy: {
      startCommand: "python scripts/run_cloud_refresh_worker.py",
      restartPolicyType: "ALWAYS",
    },
  });

  return project("auction-etl-worker-staging", {
    resources: [auctionEtlPersistentWorker],
  });
});
