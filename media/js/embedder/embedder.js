(function(window, document, undefined) {

    // When the embedder is compiled, dependencies will be loaded directly before this
    // function. Set dependencies to use no-conflict mode to avoid destroying any
    // original objects.
    var __ = _.noConflict();
    var _$ = Zepto;
    var _Backbone = Backbone.noConflict();
    var _Popcorn = Popcorn.noConflict();

    // _amara may exist with a queue of actions that need to be processed after the
    // embedder has finally loaded. Store the queue in toPush for processing in init().
    var toPush = window._amara || [];

    var Amara = function(Amara) {

        // For reference in inner functions.
        var that = this;

        // This will store all future instances of Amara-powered videos.
        // I'm trying really hard here to not use the word "widget".
        this.amaraInstances = [];

        // Private methods that are called via the push() method.
        var actions = {

            // The core function for constructing an entire video with Amara subtitles from
            // just a video URL. This includes DOM creation for the video, etc.
            embedVideo: function(options) {

                // Make sure we have a URL to work with.
                // If we do, init a new Amara view.
                if (__.has(options, 'url') && __.has(options, 'div')) {

                    that.amaraInstances.push(
                        new that.AmaraView({

                            // TODO: This needs to support a node OR ID string.
                            el: _$('#' + options.div)[0],
                            model: new that.VideoModel(options)
                        })
                    );

                }
            }
        };

        // Video model.
        this.VideoModel = _Backbone.Model.extend({

            // The initialization of these vars is unnecessary, but it's nice to know
            // what vars will *eventually* be on the video model.

            // This var will be true once we've retrieved the rest of the model attrs
            // from the Amara API.
            isComplete: false,

            // Set from within the embedder.
            div: '',
            height: '',
            initialLanguage: null,
            isOnAmara: null,
            url: '',
            width: '',

            // Set from the Amara API
            all_urls: [],
            created: null,
            description: null,
            duration: null,
            id: null,
            languages: [],
            original_language: null,
            project: null,
            resource_uri: null,
            team: null,
            thumbnail: null,
            title: null,

            // Every time a video model is created, do this.
            initialize: function() {

                var video = this;
                var apiURL = 'https://staging.universalsubtitles.org/api2/partners/videos/?&video_url=';

                // Make a call to the Amara API to get attributes like available languages,
                // internal ID, description, etc.
                _$.ajax({
                    url: apiURL + this.get('url'),
                    dataType: 'jsonp',
                    success: function(resp) {

                        if (resp.objects.length) {

                            // The video exists on Amara.
                            video.set('isOnAmara', true);

                            // There should only be one object.
                            if (resp.objects.length === 1) {

                                // Set all of the API attrs as attrs on the video model.
                                video.set(resp.objects[0]);

                                // Set the initial language to either the one provided by the initial
                                // options, or the original language from the API.
                                video.set('initialLanguage',
                                    video.get('initialLanguage') ||
                                    video.get('original_language')
                                );
                            }

                        } else {

                            // The video does not exist on Amara.
                            video.set('isOnAmara', false);

                        }

                        // Mark that the video model has been completely populated.
                        video.set('isComplete', true);
                    }
                });
            }
        });

        // Amara view. This contains all of the events and logic for a single instance of
        // an Amara-powered video.
        this.AmaraView = _Backbone.View.extend({

            initialize: function() {
                this.model.view = this;
                this.template = __.template(this.templateHTML);
                this.render();
            },

            events: {
                'click a.amara-logo':              'logoClicked',
                'click a.amara-share-button':      'shareButtonClicked',
                'click a.amara-transcript-button': 'transcriptButtonClicked',
                'click a.amara-subtitles-button':  'subtitlesButtonClicked'
            },

            render: function() {
                
                var that = this;

                // Init the Popcorn video.
                this.pop = _Popcorn.smart(this.model.get('div'), this.model.get('url'));

                this.pop.on('loadedmetadata', function() {

                    // Set the video model's height and width, now that we know it.
                    that.model.set('height', that.pop.position().height);
                    that.model.set('width', that.pop.position().width);

                    // Create the actual core DOM for the Amara container.
                    that.$el.append(that.template({
                        width: that.model.get('width')
                    }));

                    // Just set some cached Zepto selections for later use.
                    that.cacheNodes();

                    // Wait until we have a complete video model (the API was hit as soon as
                    // the video instance was created), and then retrieve the initial set
                    // of subtitles, so we can begin building out the transcript viewer
                    // and the subtitle display.
                    that.waitUntilVideoIsComplete(
                        function() {

                            // We now have a fully populated video model.
                            //
                            // Grab the subtitles for the initial language and do yo' thang.

                            if (that.model.get('isOnAmara')) {
                                console.log('We b buildin.');
                            } else {
                                // Do some other stuff for videos that aren't yet on Amara.
                            }
                        }
                    );
                });

                return this;

            },

            waitUntilVideoIsComplete: function(callback) {

                // isComplete gets set as soon as the initial API call to build out the video
                // instance has finished.
                if (!this.model.get('isComplete')) {
                    setTimeout(function() { that.waitUntilVideoIsComplete(callback); }, 100);
                } else {
                    callback();
                }
            },
            logoClicked: function() {
                alert('Logo clicked');
                return false;
            },
            shareButtonClicked: function() {
                alert('Share button clicked');
                return false;
            },
            transcriptButtonClicked: function() {
                this.$transcript.toggle();
                return false;
            },
            subtitlesButtonClicked: function() {
                alert('Subtitles button clicked');
                return false;
            },

            templateHTML: '' +
                '<div class="amara-container" style="width: {{ width }}px;">' +
                '    <div class="amara-bar">' +
                '        <a href="#" class="amara-share-button"></a>' +
                '        <a href="#" class="amara-logo">Amara</a>' +
                '        <ul class="amara-displays">' +
                '            <li><a href="#" class="amara-transcript-button"></a></li>' +
                '            <li><a href="#" class="amara-subtitles-button"></a></li>' +
                '        </ul>' +
                '    </div>' +
                '    <div class="amara-transcript">' +
                '        <div class="amara-transcript-header amara-group">' +
                '            <div class="amara-transcript-header-left">' +
                '                Auto-stream <span>ON</span>' +
                '            </div>' +
                '            <div class="amara-transcript-header-right">' +
                '                <form action="" class="amara-transcript-search">' +
                '                    <input class="amara-transcript-search-input" placeholder="Search transcript" />' +
                '                </form>' +
                '            </div>' +
                '        </div>' +
                '        <div class="amara-transcript-body">' +
                '            Transcript' +
                '        </div>' +
                '    </div>' +
                '</div>',

            cacheNodes: function() {
                this.$amaraContainer = $('div.amara-container', this.$el);
                this.$transcript = $('div.amara-transcript', this.$amaraContainer);
            }

        });

        // push() handles all action calls before and after the embedder is loaded.
        // Aside from init(), this is the only function that may be called from the
        // parent document.
        //
        // Must send push() an object with only two items:
        //     * Action  (string)
        //     * Options (object)
        //
        // Note: we don't use traditional function arguments because before the
        // embedder is loaded, _amara is just an array with a normal push() method.
        this.push = function(args) {
            
            // No arguments? Don't do anything.
            if (!arguments.length) { return; }

            // Must send push() an object with only two items.
            if (__.size(arguments[0]) === 2) {

                var action = args[0];
                var options = args[1];

                // If a method exists for this action, call it with the options.
                if (actions[action]) {
                    actions[action](options);
                }
            }

        };

        // init() gets called as soon as the embedder has finished loading.
        // Simply processes the existing _amara queue if we have one.
        this.init = function() {

            // Load the Amara CSS.
            var tag = document.getElementsByTagName('script')[0];
            var style = document.createElement('link');
            style.rel = 'stylesheet';
            style.type = 'text/css';

            // TODO: This needs to be a production URL based on DEBUG or not.
            style.href = '/site_media/css/embedder/amara.css';
            tag.parentNode.insertBefore(style, tag);

            // Change the template delimiter for Underscore templates.
            __.templateSettings = { interpolate : /\{\{(.+?)\}\}/g };

            // If we have a queue from before the embedder loaded, process the actions.
            if (toPush) {
                for (var i = 0; i < toPush.length; i++) {
                    that.push(toPush[i]);
                }
                toPush = [];
            }

            // Check to see if we have any amara-embed's to initilize.
            var amaraEmbeds = _$('div.amara-embed');

            if (amaraEmbeds.length) {
                amaraEmbeds.each(function() {

                    // This is a hack until Popcorn.js supports passing a DOM elem to
                    // its smart() method. See: http://bit.ly/L0Lb7t
                    var id = 'amara-embed-' + Math.floor(Math.random() * 100000000);
                    var $div = _$(this);
                    $div.attr('id', id);

                    // Call embedVideo with this div and URL.
                    that.push(['embedVideo', {
                        'div': id,
                        'initialLanguage': $div.data('initial-language'),
                        'url': $div.data('url')
                    }]);
                });
            }

        };

    };

    window._amara = new Amara();
    window._amara.init();

}(window, document));
