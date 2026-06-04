param projectId string
param environment string = 'dev'
param region string = 'us-central1'
param mongodbAtlasUri string
param geminApiKey string
param googleMapsApiKey string

// Variables
var agentName = 'afya-voice-orchestrator'
var firebaseProjectId = projectId
var location = region
var tags = {
  environment: environment
  project: 'afya-voice'
  track: 'mongodb'
  managedBy: 'bicep'
}

// Agent Runtime Service Account
resource agentServiceAccount 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, agentName)
  properties: {
    roleDefinitionId: '/subscriptions/${subscription().subscriptionId}/providers/Microsoft.Authorization/roleDefinitions/roles/Agent-Runtime-Admin'
    principalId: agentName
  }
}

// Secret Manager - Gemini API Key
resource geminSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'gemini-api-key'
  properties: {
    value: geminApiKey
  }
}

// Secret Manager - Google Maps API Key
resource mapsSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'google-maps-api-key'
  properties: {
    value: googleMapsApiKey
  }
}

// Secret Manager - MongoDB URI
resource mongodbSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'mongodb-atlas-uri'
  properties: {
    value: mongodbAtlasUri
  }
}

// Key Vault for Secrets
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-${environment}-${uniqueString(resourceGroup().id)}'
  location: location
  properties: {
    enabledForDeployment: true
    enabledForTemplateDeployment: true
    enabledForDiskEncryption: false
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    accessPolicies: []
  }
  tags: tags
}

// Application Insights for monitoring
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'ai-${agentName}-${environment}'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    RetentionInDays: 30
  }
  tags: tags
}

// Log Analytics Workspace
resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: 'law-${agentName}-${environment}'
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
  tags: tags
}

// Cloud Run Service (fallback option if needed)
resource cloudRunService 'Microsoft.ContainerRegistry/registries@2023-06-01-preview' = {
  name: '${replace(agentName, '-', '')}${environment}'
  location: location
  sku: {
    name: 'Standard'
  }
  properties: {
    adminUserEnabled: true
    publicNetworkAccess: 'Enabled'
  }
  tags: tags
}

// Storage Account for Build Artifacts
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: 'st${replace(agentName, '-', '')}${environment}'
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_GRS'
  }
  properties: {
    accessTier: 'Hot'
  }
  tags: tags
}

// Blob Container for agent artifacts
resource blobContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  name: '${storageAccount.name}/default/agent-artifacts'
  properties: {
    publicAccess: 'None'
  }
}

// Outputs
output agentServiceUrl string = 'https://${region}-${firebaseProjectId}.cloudfunctions.net/${agentName}'
output firebaseHostingUrl string = 'https://${firebaseProjectId}.web.app'
output keyVaultName string = keyVault.name
output appInsightsInstrumentationKey string = appInsights.properties.InstrumentationKey
output containerRegistryLoginServer string = cloudRunService.properties.loginServer
