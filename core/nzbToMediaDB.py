# coding=utf-8
from __future__ import with_statement

import re
import sqlite3
import time

import core
from core import logger


def dbFilename(filename="nzbtomedia.db", suffix=None):
    """
    @param filename: The sqlite database filename to use. If not specified,
                     will be made to be nzbtomedia.db
    @param suffix: The suffix to append to the filename. A '.' will be added
                   automatically, i.e. suffix='v0' will make dbfile.db.v0
    @return: the correct location of the database file.
    """
    if suffix:
        filename = "%s.%s" % (filename, suffix)
    return core.os.path.join(core.PROGRAM_DIR, filename)


class DBConnection:
    def __init__(self, filename="nzbtomedia.db", suffix=None, row_type=None):

        self.filename = filename
        self.connection = sqlite3.connect(dbFilename(filename), 20)
        if row_type == "dict":
            self.connection.row_factory = self._dict_factory
        else:
            self.connection.row_factory = sqlite3.Row

    def checkDBVersion(self):
        result = None
        try:
            result = self.select("SELECT db_version FROM db_version")
        except sqlite3.OperationalError, e:
            if "no such table: db_version" in e.args[0]:
                return 0

        if result:
            return int(result[0]["db_version"])
        else:
            return 0

    def fetch(self, query, args=None):
        if query == None:
            return

        sqlResult = None
        attempt = 0

        while attempt < 5:
            try:
                if args == None:
                    logger.log(self.filename + ": " + query, logger.DB)
                    cursor = self.connection.cursor()
                    cursor.execute(query)
                    sqlResult = cursor.fetchone()[0]
                else:
                    logger.log(self.filename + ": " + query + " with args " + str(args), logger.DB)
                    cursor = self.connection.cursor()
                    cursor.execute(query, args)
                    sqlResult = cursor.fetchone()[0]

                # get out of the connection attempt loop since we were successful
                break
            except sqlite3.OperationalError, e:
                if "unable to open database file" in e.args[0] or "database is locked" in e.args[0]:
                    logger.log(u"DB error: " + str(e), logger.WARNING)
                    attempt += 1
                    time.sleep(1)
                else:
                    logger.log(u"DB error: " + str(e), logger.ERROR)
                    raise
            except sqlite3.DatabaseError, e:
                logger.log(u"Fatal error executing query: " + str(e), logger.ERROR)
                raise

        return sqlResult

    def mass_action(self, querylist, logTransaction=False):
        if querylist == None:
            return

        sqlResult = []
        attempt = 0

        while attempt < 5:
            try:
                for qu in querylist:
                    if len(qu) == 1:
                        if logTransaction:
                            logger.log(qu[0], logger.DEBUG)
                        sqlResult.append(self.connection.execute(qu[0]))
                    elif len(qu) > 1:
                        if logTransaction:
                            logger.log(qu[0] + " with args " + str(qu[1]), logger.DEBUG)
                        sqlResult.append(self.connection.execute(qu[0], qu[1]))
                self.connection.commit()
                logger.log(u"Transaction with " + str(len(querylist)) + u" query's executed", logger.DEBUG)
                return sqlResult
            except sqlite3.OperationalError, e:
                sqlResult = []
                if self.connection:
                    self.connection.rollback()
                if "unable to open database file" in e.args[0] or "database is locked" in e.args[0]:
                    logger.log(u"DB error: " + str(e), logger.WARNING)
                    attempt += 1
                    time.sleep(1)
                else:
                    logger.log(u"DB error: " + str(e), logger.ERROR)
                    raise
            except sqlite3.DatabaseError, e:
                sqlResult = []
                if self.connection:
                    self.connection.rollback()
                logger.log(u"Fatal error executing query: " + str(e), logger.ERROR)
                raise

        return sqlResult

    def action(self, query, args=None):
        if query == None:
            return

        sqlResult = None
        attempt = 0

        while attempt < 5:
            try:
                if args == None:
                    logger.log(self.filename + ": " + query, logger.DB)
                    sqlResult = self.connection.execute(query)
                else:
                    logger.log(self.filename + ": " + query + " with args " + str(args), logger.DB)
                    sqlResult = self.connection.execute(query, args)
                self.connection.commit()
                # get out of the connection attempt loop since we were successful
                break
            except sqlite3.OperationalError, e:
                if "unable to open database file" in e.args[0] or "database is locked" in e.args[0]:
                    logger.log(u"DB error: " + str(e), logger.WARNING)
                    attempt += 1
                    time.sleep(1)
                else:
                    logger.log(u"DB error: " + str(e), logger.ERROR)
                    raise
            except sqlite3.DatabaseError, e:
                logger.log(u"Fatal error executing query: " + str(e), logger.ERROR)
                raise

        return sqlResult

    def select(self, query, args=None):

        sqlResults = self.action(query, args).fetchall()

        if sqlResults == None:
            return []

        return sqlResults

    def upsert(self, tableName, valueDict, keyDict):

        changesBefore = self.connection.total_changes

        genParams = lambda myDict: [x + " = ?" for x in myDict.keys()]

        query = "UPDATE " + tableName + " SET " + ", ".join(genParams(valueDict)) + " WHERE " + " AND ".join(
            genParams(keyDict))

        self.action(query, valueDict.values() + keyDict.values())

        if self.connection.total_changes == changesBefore:
            query = "INSERT OR IGNORE INTO " + tableName + " (" + ", ".join(valueDict.keys() + keyDict.keys()) + ")" + \
                    " VALUES (" + ", ".join(["?"] * len(valueDict.keys() + keyDict.keys())) + ")"
            self.action(query, valueDict.values() + keyDict.values())

    def tableInfo(self, tableName):
        # FIXME ? binding is not supported here, but I cannot find a way to escape a string manually
        cursor = self.connection.execute("PRAGMA table_info(%s)" % tableName)
        columns = {}
        for column in cursor:
            columns[column['name']] = {'type': column['type']}
        return columns

    # http://stackoverflow.com/questions/3300464/how-can-i-get-dict-from-sqlite-query
    def _dict_factory(self, cursor, row):
        d = {}
        for idx, col in enumerate(cursor.description):
            d[col[0]] = row[idx]
        return d


def sanityCheckDatabase(connection, sanity_check):
    sanity_check(connection).check()


class DBSanityCheck(object):
    def __init__(self, connection):
        self.connection = connection

    def check(self):
        pass


# ===============
# = Upgrade API =
# ===============

def upgradeDatabase(connection, schema):
    logger.log(u"Checking database structure...", logger.MESSAGE)
    _processUpgrade(connection, schema)


def prettyName(class_name):
    return ' '.join([x.group() for x in re.finditer("([A-Z])([a-z0-9]+)", class_name)])


def _processUpgrade(connection, upgradeClass):
    instance = upgradeClass(connection)
    logger.log(u"Checking " + prettyName(upgradeClass.__name__) + " database upgrade", logger.DEBUG)
    if not instance.test():
        logger.log(u"Database upgrade required: " + prettyName(upgradeClass.__name__), logger.MESSAGE)
        try:
            instance.execute()
        except sqlite3.DatabaseError, e:
            print "Error in " + str(upgradeClass.__name__) + ": " + str(e)
            raise
        logger.log(upgradeClass.__name__ + " upgrade completed", logger.DEBUG)
    else:
        logger.log(upgradeClass.__name__ + " upgrade not required", logger.DEBUG)

    for upgradeSubClass in upgradeClass.__subclasses__():
        _processUpgrade(connection, upgradeSubClass)


# Base migration class. All future DB changes should be subclassed from this class
class SchemaUpgrade(object):
    def __init__(self, connection):
        self.connection = connection

    def hasTable(self, tableName):
        return len(self.connection.action("SELECT 1 FROM sqlite_master WHERE name = ?;", (tableName,)).fetchall()) > 0

    def hasColumn(self, tableName, column):
        return column in self.connection.tableInfo(tableName)

    def addColumn(self, table, column, type="NUMERIC", default=0):
        self.connection.action("ALTER TABLE %s ADD %s %s" % (table, column, type))
        self.connection.action("UPDATE %s SET %s = ?" % (table, column), (default,))

    def checkDBVersion(self):
        result = self.connection.select("SELECT db_version FROM db_version")
        if result:
            return int(result[-1]["db_version"])
        else:
            return 0

    def incDBVersion(self):
        new_version = self.checkDBVersion() + 1
        self.connection.action("UPDATE db_version SET db_version = ?", [new_version])
        return new_version
