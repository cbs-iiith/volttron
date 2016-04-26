'use strict';

var keyMirror = require('react/lib/keyMirror');

module.exports = keyMirror({
    OPEN_MODAL: null,
    CLOSE_MODAL: null,

    TOGGLE_CONSOLE: null,

    UPDATE_COMPOSER_VALUE: null,

    MAKE_REQUEST: null,
    FAIL_REQUEST: null,
    RECEIVE_RESPONSE: null,

    RECEIVE_AUTHORIZATION: null,
    RECEIVE_UNAUTHORIZED: null,
    CLEAR_AUTHORIZATION: null,

    REGISTER_PLATFORM_ERROR: null,
    DEREGISTER_PLATFORM_ERROR: null,

    RECEIVE_PLATFORMS: null,
    RECEIVE_PLATFORM: null,
    RECEIVE_PLATFORM_ERROR: null,
    CLEAR_PLATFORM_ERROR: null,

    RECEIVE_PLATFORM_TOPIC_DATA: null,

    SCAN_FOR_DEVICES: null,
    CANCEL_SCANNING: null,
    LIST_DETECTED_DEVICES: null,
    CONFIGURE_DEVICE: null,
    EDIT_REGISTRY: null,
    LOAD_REGISTRY: null,
    GENERATE_REGISTRY: null,
    CANCEL_REGISTRY: null,
    SAVE_REGISTRY: null,

    TOGGLE_TAPTIP: null,
    HIDE_TAPTIP: null,
    SHOW_TAPTIP: null,
    CLEAR_BUTTON: null,
});
