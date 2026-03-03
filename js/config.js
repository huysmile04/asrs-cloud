'use strict';

const CONFIG = {
  mqtt: {
    host: process.env.MQTT_HOST || 'localhost',
    port: process.env.MQTT_PORT || 1883,
    clientId: process.env.MQTT_CLIENT_ID || 'mqtt_client',
    username: process.env.MQTT_USERNAME || '',
    password: process.env.MQTT_PASSWORD || ''
  },
  warehouse: {
    location: process.env.WAREHOUSE_LOCATION || 'Default Location',
    capacity: process.env.WAREHOUSE_CAPACITY || 1000
  },
  ui: {
    theme: process.env.UI_THEME || 'light',
    language: process.env.UI_LANGUAGE || 'en'
  },
  system: {
    maintenanceMode: process.env.MAINTENANCE_MODE || false,
    version: '1.0.0'
  }
};

module.exports = CONFIG;