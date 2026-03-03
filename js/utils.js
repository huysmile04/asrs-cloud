// Utility functions for validation, formatting, event handling, storage, and helpers

// Validation function to check if a value is a valid email
function isValidEmail(email) {
    const re = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
    return re.test(String(email).toLowerCase());
}

// Formatting function to format date into a readable string
function formatDate(date) {
    return date.toISOString().split('T')[0];
}

// Event handling function to add an event listener
function addEvent(el, event, callback) {
    if (el && el.addEventListener) {
        el.addEventListener(event, callback);
    }
}

// Storage function to save data in local storage
function saveToLocalStorage(key, value) {
    localStorage.setItem(key, JSON.stringify(value));
}

// Helper method to generate a unique ID
function generateUniqueID() {
    return 'xxxx-xxxx-xxxx'.replace(/x/g, function() {
        return Math.floor(Math.random() * 16).toString(16);
    });
}
