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
            div: '',
            height: '',
            url: '',
            width: ''
        });

        // Amara view. This contains all of the events and logic for a single instance of
        // an Amara-powered video.
        this.AmaraView = _Backbone.View.extend({

            initialize: function() {
                this.model.view = this;

                // Variables that will eventually be set after rendering.
                this.$amaraContainer = null;
                this.pop = null;

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

                // TODO: Popcorn is not firing any events for any video types other
                // than HTML5. Watch http://popcornjs.org/popcorn-docs/events/.
                this.pop.on('loadedmetadata', function() {

                    // Set the video model's height and width, now that we know it.
                    that.model.set('height', that.pop.position().height);
                    that.model.set('width', that.pop.position().width);

                    that.$el.append(that.template({
                        width: that.model.get('width')
                    }));

                    that.$amaraContainer = $('div.amara-container', that.$el);
                });

                return this;

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
                alert('Transcript button clicked');
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
                '    </div>' +
                '</div>'

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
                    that.push(['embedVideo', {'div': id, 'url': $div.data('url') }]);
                });
            }

        };

    };

    window._amara = new Amara();
    window._amara.init();

}(window, document));
