from __future__ import absolute_import

import logging
import json
import random
import string
from functools import wraps

from flask import (render_template, request, redirect, url_for,
                   flash, session, abort, make_response, jsonify)
from flask_login import login_user, login_required, logout_user, current_user

from sqlalchemy import asc, desc
from sqlalchemy.orm.exc import NoResultFound

from . import app, models, auth, csrf


db_session = models.db_session


def catch_exceptions(f):
    """Useful decorator for debugging
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception:
            logging.error("Unhandled Error on %s" % f.__name__,
                          exc_info=True)
            return abort(500)
    return wrapper


def get_ordered_categories():
    categories = db_session.query(models.Category) \
                           .order_by(asc(models.Category.name))
    return categories


#############
#
# Main Route
#
#############

@app.route('/')
@app.route('/catalog/')
def index():
    """Front page"""
    # print "session: {}".format(session)
    categories = db_session.query(models.Category) \
                           .order_by(asc(models.Category.name))
    items = db_session.query(models.Item) \
                      .order_by(desc(models.Item.updated_date))[:10]
    return render_template('index.html',
                           categories=categories,
                           items=items)


@app.route("/json/")
@app.route("/catalog/json/")
def indexJson():
    """Json version of front page"""
    categories = db_session.query(models.Category) \
                           .order_by(asc(models.Category.name))
    items = db_session.query(models.Item) \
                      .order_by(desc(models.Item.updated_date))[:10]

    # Make json response
    results = {"Categories": [c.serialize for c in categories],
               "Items": [i.serialize for i in items]}

    return jsonify(results)


##################
#
# Category Routes
#
##################

@app.route('/catalog/new/', methods=['GET', 'POST'])
@login_required
def NewCategory():
    # if 'username' not in session:
    #     return redirect('/login')
    if request.method == 'POST':
        new = models.Category(name=request.form['name'])
        db_session.add(new)
        db_session.commit()
        return redirect(url_for('index'))
    else:
        return render_template('newCategory.html')


@app.route("/catalog/<string:category_name>/")
@app.route("/catalog/<string:category_name>/items/")
def ShowCategory(category_name):
    # Get category
    try:
        category = db_session.query(models.Category) \
                             .filter_by(name=category_name).one()
        items = db_session.query(models.Item).join(models.Category) \
                          .filter(models.Category.name == category_name).all()
    except NoResultFound:
        return abort(404)
    except Exception:
        logging.error("Unhandled error in ShowCategory", exc_info=True)
        return abort(500)

    return render_template("showCategory.html",
                           items=items,
                           category=category,
                           categories=get_ordered_categories())


@app.route("/catalog/<string:category_name>/json/")
@app.route("/catalog/<string:category_name>/items/json/")
def ShowCategoryJson(category_name):
    # Get category
    try:
        category = db_session.query(models.Category) \
                             .filter_by(name=category_name).one()
        items = db_session.query(models.Item).join(models.Category) \
                          .filter(models.Category.name == category_name).all()
    except NoResultFound:
        return abort(404)
    except Exception:
        logging.error("", exc_info=True)
        return abort(500)

    # Make json response
    results = {"Category": category.serialize,
               "Items": [i.serialize for i in items]}

    return jsonify(results)


@app.route('/catalog/<string:category_name>/<string:item_name>/')
def ShowItem(category_name, item_name):
    """View of a single item"""
    try:
        category, item = (
            db_session.query(models.Category, models.Item)
                      .filter(models.Category.id == models.Item.category_id)
                      .filter(models.Category.name == category_name)
                      .filter(models.Item.name == item_name).one())
    except NoResultFound:
        return abort(404)
    except Exception:
        logging.error("something went wrong", exc_info=True)
        return abort(500)
    return render_template("showItem.html",
                           category=category,
                           item=item)


@app.route('/catalog/<string:category_name>/<string:item_name>/json/')
def ShowItemJson(category_name, item_name):
    """View of a single item"""
    try:
        category, item = (
            db_session.query(models.Category, models.Item)
                      .filter(models.Category.id == models.Item.category_id)
                      .filter(models.Category.name == category_name)
                      .filter(models.Item.name == item_name).one())
    except NoResultFound:
        return abort(404)
    except Exception:
        logging.error("Unhandled error in ShowItemJson", exc_info=True)
        return abort(500)

    # Make json response
    return jsonify(item.serialize)


@app.route('/catalog/<string:category_name>/<string:item_name>/edit/',
           methods=['GET', 'POST'])
@login_required
def EditItem(category_name, item_name):
    """View for editing an item. Only accessible by item's owner."""
    # Get Item
    try:
        category, item = (
            db_session.query(models.Category, models.Item)
                      .filter(models.Category.id == models.Item.category_id)
                      .filter(models.Category.name == category_name)
                      .filter(models.Item.name == item_name).one())
    except NoResultFound:
        return abort(404)
    except Exception:
        logging.error("something went wrong", exc_info=True)
        return abort(500)

    # Only owner can perform this action
    # current_user.get_id will return None if user is not logged in
    if item.user.id != int(current_user.get_id()):
        return abort(403)

    if request.method == 'POST':
        # Check 1: Ensure that all fields are passed back and has value
        # "If not all required fields are passed back or not all fields are "
        # "filled"
        if not all([field in request.form and request.form[field]
                    for field in ("name", "description")]):
            flash("Error: All fields are required!")
            return render_template(
                "editItem.html",
                name=request.form.get("name", ""),
                description=request.form.get("description", ""),
                category=category)

        # Check 2: for duplicate item
        existing = db_session.query(models.Item) \
                             .filter_by(name=request.form["name"],
                                        category_id=category.id).all()

        # If user is entering duplicate item, stop this transaction
        if existing:
            flash("Error: Item with duplicate name/category combination "
                  "found.")
            return render_template(
                "editItem.html",
                name=request.form.get("name", ""),
                description=request.form.get("description", ""))

        # Edit item
        item.name = request.form["name"]
        item.description = request.form["description"]

        db_session.add(item)
        db_session.commit()
        flash("Edit Successful!")
        return redirect(url_for("ShowCategory",
                                category_name=category.name))

    else:
        return render_template("editItem.html",
                               name=item.name,
                               description=item.description,
                               category=category)


@app.route('/catalog/<string:category_name>/<string:item_name>/delete/',
           methods=["GET", "POST"])
@login_required
def DeleteItem(category_name, item_name):
    """View for deleting an item. Only accessible by item's owner."""
    # Get item and category
    try:
        category, item = (
            db_session.query(models.Category, models.Item)
                      .filter(models.Category.id == models.Item.category_id)
                      .filter(models.Category.name == category_name)
                      .filter(models.Item.name == item_name).one())
    except NoResultFound:
        return abort(404)
    except Exception:
        logging.error("something went wrong", exc_info=True)
        return abort(500)

    # Only owner can perform this action
    # current_user.get_id will return None if user is not logged in
    if item.user.id != int(current_user.get_id()):
        return abort(403)

    if request.method == 'POST':
        if 'confirm' in request.form and request.form["confirm"] == "true":
            item_name = item.name  # Save the name for use later
            db_session.delete(item)
            db_session.commit()
            flash('Deleted %s' % item_name)
            return redirect(url_for('ShowCategory',
                                    category_name=category_name))
    else:
        return render_template('deleteItem.html',
                               category=category,
                               name=item.name)


@app.route('/catalog/item/new/', methods=['GET', 'POST'])
@login_required
def NewItem():
    """View for creating a new item. User must be logged in"""
    # This will be useful later
    categories = get_ordered_categories()

    if request.method == 'POST':
        # Check 1: Ensure that all fields are passed back and has value
        # "If not all required fields are passed back or not all fields are "
        # "filled"
        if not all([field in request.form and request.form[field]
                    for field in ("name", "description", "category")]):
            flash("Error: All fields are required!")
            return render_template(
                "newItem.html",
                categories=categories,
                name=request.form.get("name", ""),
                description=request.form.get("description", ""),
                category=request.form.get("category", ""))

        # Attempt to create new item
        category = db_session.query(models.Category) \
                             .filter_by(name=request.form["category"]) \
                             .one()
        existing = db_session.query(models.Item) \
                             .filter_by(name=request.form["name"],
                                        category_id=category.id).all()

        # If user is entering duplicate item, stop this transaction
        if existing:
            flash("Error: Item with duplicate name/category combination "
                  "found.")
            return render_template(
                "newItem.html",
                categories=categories,
                name=request.form.get("name", ""),
                description=request.form.get("description", ""),
                category=request.form.get("category", ""))

        # Continue with item creation
        item = models.Item(name=request.form["name"],
                           description=request.form["description"],
                           category_id=category.id,
                           user_id=int(current_user.get_id()))
        db_session.add(item)
        db_session.commit()
        return redirect(url_for("ShowCategory",
                        category_name=category.name))

    else:
        return render_template("newItem.html",
                               categories=categories)


# Delete a category. Not used
# @app.route('/catalog/<int:category_id>/delete/', methods=['GET', 'POST'])
def DeleteCategory(category_id):
    # if 'username' not in session:
    #     return redirect('/login')
    try:
        category = db_session.query(models.Category) \
                             .filter_by(id=category_id).one()
    except Exception:
        raise

    db_session.delete(category)
    db_session.commit()


@app.route('/login/', methods=['GET', 'POST'])
def Login():
    """Main login view that supports basic form based login and OAuth login.
    OAuth logins are initiated here as well, but through a separate mechanism
    initiated by client-side code.
    """

    # Anti x-site forgery attack
    state = ''.join(random.choice(string.ascii_uppercase + string.digits)
                    for x in xrange(32))
    session['state'] = state

    # Handle POST request (submit user/pass)
    if request.method == "POST":
        if "username" not in request.form or "password" not in request.form:
            flash("Username or password missing")
            return render_template("login.html",
                                   STATE=state,
                                   username=request.form.get("username", ""),
                                   password=request.form.get("password", ""),
                                   fb_app_id=auth.get_fb_app_id())
        # Login and validate the user.
        # user should be an instance of your `User` class
        try:
            username = request.form.get("username")
            password = request.form.get("password")


            user = (db_session.query(models.User)
                              .filter_by(username=username,
                                         isoauth=False)
                              .one())

            # check hashed pw
            if auth.make_pw_hash(str(username),
                                 str(password),
                                 str(user.password)) != user.password:
                # Technically not the right error to raise, but we want the
                # same results
                raise NoResultFound

        except NoResultFound:
            flash("Incorrect credentials")
            return render_template("login.html",
                                   STATE=state,
                                   username=username,
                                   password="",
                                   fb_app_id=auth.get_fb_app_id())
        except Exception:
            logging.error("Unhandled error in Login!", exc_info=True)
            abort(500)

        # Successful login if we can find corresponding user
        login_user(user)

        flash('Logged in successfully.')

        next_url = request.args.get('next')

        # is_safe_url should check if the url is safe for redirects.
        # See http://flask.pocoo.org/snippets/62/ for an example.
        if not auth.is_safe_url(next_url):
            return abort(500)

        return redirect(next_url or url_for("index"))

    # Render page for GET request
    else:
        return render_template("login.html",
                               STATE=state,
                               fb_app_id=auth.get_fb_app_id())


@app.route("/logout/")
@login_required
def Logout():
    """Generic logout view. Handles OAuth as well"""
    if "session_info" in session:
        if session["session_info"]["provider"] == auth.PROVIDER_FACEBOOK:
            # Have facebook revoke access token
            fbdisconnect()
        elif session["session_info"]["provider"] == auth.PROVIDER_GOOGLE:
            # TODO Have google revoke the token
            pass
        del session["session_info"]
    logout_user()
    flash("Successfully logged out!")
    return redirect(request.args.get('next') or url_for("index"))


@csrf.exempt
@app.route('/fbconnect', methods=['POST'])
def fbconnect():
    """URL accessed by client-side oauth login code."""
    # Protect against cross site reference forgery attacks
    if request.args.get('state') != session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Exchange client token for a long-lived server-side token
    access_token = request.data

    # Get session info. Facebook sessio info object has the format
    # {"provider": "provider",
    #  "user": "name",
    #  "email": "email",
    #  "facebook_id": "id",
    #  "access_token": "stored_token",
    #  "picture": "picture_data"}
    session_info = auth.build_facebook_session(access_token)

    # Check if we got all the required data back. If not, flash an error
    # and return to login page
    if session_info is None:
        Logout()
        response = make_response(json.dumps("Failed to exchange access token "
                                            "for server-side token."), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Add session info to session
    session["session_info"] = session_info

    # Get or create user
    user = auth.query_oauth_user(session_info['email'])
    if not user:
        user = auth.create_user(username=session_info["user"],
                                email=session_info["email"],
                                isoauth=True)

    # Login to our system
    login_user(user)

    # Return success response
    response = make_response(json.dumps(
        "Now logged in as %s" % session["session_info"]["user"]),
        200)
    response.headers['Content-Type'] = 'application/json'
    return response


def fbdisconnect():
    """Make HTTP to Facebook to revoke access token. Doesn't do anything about
    the session or session objects!!!"""
    if "session_info" not in session:
        # For whatever reason, the given token was invalid.
        response = json.dumps("Doesn't look like you were logged in")
    else:
        response = auth.fb_disconnect(session["session_info"])
    return response


# Simple HTTP error handling
@app.errorhandler(404)
def not_found(error):
    # return str(error), 404
    return render_template('404.html'), 404


# Simple HTTP error handling
@app.errorhandler(500)
def internal_error(error):
    # return str(error), 500
    return render_template('500.html'), 500
