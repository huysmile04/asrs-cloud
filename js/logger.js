'use strict';

class Logger {
    constructor() {
        this.levels = {
            info: 'INFO',
            warn: 'WARN',
            error: 'ERROR',
            success: 'SUCCESS'
        };
    }

    log(message, level) {
        const timestamp = new Date().toISOString();
        const formattedMessage = `[${timestamp}] [${this.levels[level] || 'INFO'}]: ${message}`;
            console.log(formattedMessage);
            // For demonstration, we can use alerts for warnings and errors.
        if (level === 'warn' || level === 'error') {
            alert(formattedMessage);
        }
    }

    info(message) {
        this.log(message, 'info');
    }

    warn(message) {
        this.log(message, 'warn');
    }

    error(message) {
        this.log(message, 'error');
    }

    success(message) {
        this.log(message, 'success');
    }
}

// Example usage:
const logger = new Logger();
logger.info('This is an info message.');
logger.warn('This is a warning message.');
logger.error('This is an error message.');
logger.success('This is a success message.');
