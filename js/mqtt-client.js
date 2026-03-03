// mqtt-client.js

class MQTTClient {
    constructor(brokerUrl, options) {
        this.brokerUrl = brokerUrl;
        this.options = options;
        this.client = null;
        this.connect();
    }

    connect() {
        this.client = new Paho.MQTT.Client(this.brokerUrl);
        this.client.onConnectionLost = this.onConnectionLost.bind(this);
        this.client.onMessageArrived = this.onMessageArrived.bind(this);
        this.reconnect();
    }

    reconnect() {
        this.client.connect({
            ...this.options,
            onSuccess: this.onConnect.bind(this),
            onFailure: this.onFailure.bind(this)
        });
    }

    onConnect() {
        console.log('Connected to MQTT broker');
    }

    onFailure(error) {
        console.error('Connection failed: ', error);
        setTimeout(() => this.reconnect(), 5000);
    }

    subscribe(topic) {
        this.client.subscribe(topic);
    }

    onMessageArrived(message) {
        console.log('Message arrived: ' + message.payloadString);
        // Handle message here
    }

    sendMessage(topic, message) {
        const msg = new Paho.MQTT.Message(message);
        msg.destinationName = topic;
        this.client.send(msg);
    }

    onConnectionLost(responseObject) {
        if (responseObject.errorCode !== 0) {
            console.log('Connection lost: ' + responseObject.errorMessage);
            this.reconnect();
        }
    }
}

// Usage example
const mqttClient = new MQTTClient('ws://broker.hivemq.com:8000/mqtt', {clientId: 'myClientId'});