#!/bin/bash
# Deploy BabelChef Live Translator to Cloud Run
set -euo pipefail

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-mise-chef-app}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
SERVICE_NAME="babelchef-live-translator"

echo "🍳 Deploying BabelChef Live Translator to Cloud Run..."
echo "   Project: $PROJECT_ID"
echo "   Region:  $REGION"
echo "   Service: $SERVICE_NAME"

gcloud run deploy "$SERVICE_NAME" \
    --source . \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --allow-unauthenticated \
    --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_CLOUD_LOCATION=$REGION,GOOGLE_GENAI_USE_VERTEXAI=TRUE" \
    --memory 1Gi \
    --cpu 1 \
    --timeout 3600 \
    --session-affinity \
    --min-instances 0 \
    --max-instances 5

echo "✅ Deployment complete!"
echo "   URL: $(gcloud run services describe $SERVICE_NAME --project $PROJECT_ID --region $REGION --format 'value(status.url)')"
