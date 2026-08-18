#!/bin/bash
#
# Script to test the API locally
#

echo "🧪 Testing API Géo locally..."
echo ""

API_URL="http://localhost:8000"

# Test 1: Health check
echo "1️⃣  Testing health endpoint..."
curl -s "${API_URL}/health" | python3 -m json.tool
echo ""
echo ""

# Test 2: Stats
echo "2️⃣  Testing stats endpoint..."
curl -s "${API_URL}/stats" | python3 -m json.tool | head -20
echo ""
echo ""

# Test 3: Get Paris
echo "3️⃣  Testing get commune by code (Paris - 75056)..."
curl -s "${API_URL}/communes/75056" | python3 -m json.tool | head -30
echo ""
echo ""

# Test 4: Search by name
echo "4️⃣  Testing search by name (paris)..."
curl -s "${API_URL}/communes/search/paris?limit=3" | python3 -m json.tool
echo ""
echo ""

# Test 5: List communes by department
echo "5️⃣  Testing list communes by department (75)..."
curl -s "${API_URL}/communes?departement=75&limit=5" | python3 -m json.tool
echo ""
echo ""

echo "✅ All tests completed!"
echo ""
echo "Full documentation: ${API_URL}/docs"
