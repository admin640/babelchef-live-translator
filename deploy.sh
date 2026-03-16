#!/bin/bash
# Deploy BabelChef Live Translator to Cloud Run
set -euo pipefail

# Source .env first to load LiveKit secrets
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

PROJECT_ID="mise-chef-app"
REGION="us-central1"
SERVICE_NAME="babelchef-live-translator"

gcloud run deploy "$SERVICE_NAME" \
    --source . \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --allow-unauthenticated \
    --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_CLOUD_LOCATION=$REGION,GOOGLE_GENAI_USE_VERTEXAI=TRUE,LIVEKIT_URL=$LIVEKIT_URL,LIVEKIT_API_KEY=$LIVEKIT_API_KEY,LIVEKIT_API_SECRET=$LIVEKIT_API_SECRET" \
    --memory 1Gi \
    --cpu 1 \
    --timeout 3600 \
    --session-affinity \
    --min-instances 0 \
    --max-instances 5

echo "✅ Deployment complete!"
echo "   URL: $(gcloud run services describe $SERVICE_NAME --project $PROJECT_ID --region $REGION --format 'value(status.url)')"
