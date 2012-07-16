#!/bin/bash

# Abort if any error
set -e

date

# Git pull with retries
successful_pull=""
set +e

for retry in 1 2 3 4 5; do
   git pull
   rc="$?"

   if [ "$rc" = "0" ]; then
      successful_pull="true"
      break
   fi

   echo "git pull returned $rc, retrying..."
   sleep 120
done
set -e

if [ "$successful_pull" != "true" ]; then
   echo "unable to git pull"
   exit 1
fi

echo "makemessages"
cd ..
python manage.py makemessages -i deploy\* -i media\js\closure-library\* -i media/js/unisubs-calcdeps.js.py -a
python manage.py makemessages -d djangojs -i deploy\* -i media\js\closure-library\* -i media/js/unisubs-calcdeps.js.py -a

echo "pushing to transifex"
tx push --source

echo "pulling from transifex"
tx pull -a

echo "compiling messages"
python manage.py compilemessages

echo "adding to git"
git add locale/*/LC_MESSAGES/django.*o

echo "committing to rep"
git commit -m "Updated transifex translations -- through update_translations.sh"

echo "pushing to rep"
date

git push 
# in order for this to work, you must have a ~/.transifexrc file (kept out of source control since it requires a passwords)

exit
