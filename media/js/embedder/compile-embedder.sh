#!/bin/bash

cat media/js/embedder/json2.min.js \
    media/js/embedder/underscore.min.js \
    media/js/embedder/zepto.min.js \
    media/js/embedder/backbone.min.js \
    media/js/embedder/popcorn.js \
    media/js/embedder/embedder.js \
    > media/js/embedder/amara.js
