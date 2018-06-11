import sqlite3
import sys
import json
import natto
import math
import numpy
import unicodedata
import string
import re

class Document():
    """Abstract class representing a document.
    """

    def id(self):
        """Returns the id for the Document. Should be unique within the Collection.
        """
        raise NotImplementedError()
    
    def text(self):
        """Returns the text for the Document.
        """
        raise NotImplementedError()

class Collection():
    """Abstract class representing a collection of documents.
    """

    def get_document_by_id(self, id):
        """Gets the document for the given id.
        
        Returns:
            Document: The Document for the given id.
        """
        raise NotImplementedError()

    def num_documents(self):
        """Returns the number of documents.
        
        Returns:
            int: The number of documents in the collection.
        """
        raise NotImplementedError()

    def get_all_documents(self):
        """Creates an iterator that iterates through all documents in the collection.
        
        Returns:
            Iterable[Document]: All the documents in the collection.
        """
        raise NotImplementedError()

class WikipediaArticle(Document):
    """A Wikipedia article.

    Attributes:
        title (str): The title. This will be unique so it can be used as the id. It will also always be less than 256 bytes.
        _text (str): The plain text version of the article body.
        opening_text (str): The first paragraph of the article body.
        auxiliary_text (List[str]): A list of auxiliary text, usually from the inbox.
        categories (List[str]): A list of categories.
        headings (List[str]): A list of headings (i.e. the table of contents).
        wiki_text (str): The MediaWiki markdown source.
        popularity_score(float): Some score indicating article popularity. Bigger is more popular.
        num_incoming_links(int): Number of links (within Wikipedia) that point to this article.
    """
    def __init__(self, collection, title, text, opening_text, auxiliary_text, categories, headings, wiki_text, popularity_score, num_incoming_links):
        self.title = title
        self._text = text
        self.opening_text = opening_text
        self.auxiliary_text = auxiliary_text # list
        self.categories = categories
        self.headings = headings
        self.wiki_text = wiki_text
        self.popularity_score = popularity_score
        self.num_incoming_links = num_incoming_links

    def id(self):
        """Returns the id for the WikipediaArticle, which is its title.

        Override for Document.

        Returns:
            str: The id, which in the Wikipedia article's case, is the title.
        """
        return self.title

    def text(self):
        """Returns the text for the Document.

        Override for Document.

        Returns:
            str: Text for the Document
        """
        return self._text

class FilterWords():
    def shouldBeIncluded(feature):
        if feature[0] == '名詞':
            if feature[1] == 'サ変接続' or feature[1] == '一般' or feature[1] == '形容動詞語幹' or feature[1] == '固有名詞' or feature[1] == '数':
                return True
        elif feature[0] == '形容詞':
            if feature[1] == '自立':
                return True
        elif feature[0] == '動詞':
            if feature[1] == '自立':
                return True
        return False

    def excludeParticles(features):
        return features[0] != '助詞'

class AnalyseQuery():

    def extractWords(self, query, func = FilterWords.shouldBeIncluded):
        parser = natto.MeCab()
        terms = []
        for node in parser.parse(query, as_nodes=True):
            if node.is_nor():
                features = node.feature.split(',')
                # if features[0] != '助詞':
                if func(features):
                    terms.append(features[6] if len(features) == 9 else node.surface)
        return terms

    def divide_ngrams(self, query):
        n = 2
        table_for_remove = str.maketrans("", "", string.punctuation  + "「」、。・『』《》")
        ngrams = unicodedata.normalize("NFKC", query.strip().replace(" ", ""))
        ngrams = ngrams.translate(table_for_remove)
        ngrams = re.sub(r'[a-zA-Z0-9¥"¥.¥,¥@]+', '', ngrams, flags=re.IGNORECASE)
        ngrams = re.sub(r'[!"“#$%&()\*\+\-\.,\/:;<=>?@\[\\\]^_`{|}~]', '', ngrams, flags=re.IGNORECASE)
        ngrams = re.sub(r'[\n|\r|\t|年|月|日]', '', ngrams, flags=re.IGNORECASE)

        ngrams = [ngrams[i:i+n] for i in range(0, len(ngrams))]
        return ngrams

class Index():

    def __init__(self, filename, collection):
        self.db = sqlite3.connect(filename)
        self.collection = collection

    def search(self, terms):
        c = self.db.cursor()

        # search process
        print("extractWords Done")

        # titles which apeare len(query) times are the rets
        titles = []
        flag = True
        for term in terms:
            cands = c.execute("SELECT document_id FROM postings WHERE term=?", (term,)).fetchall()
            if cands == None: # TODO: len(cands) == 0
                continue
            """
            for cand in cands:
                if cand[0] in dict:
                    dict[cand[0]] += 1
                else:
                    dict[cand[0]] = 1
                if dict[cand[0]] == len(terms):
                    titles.append(cand[0])
            """

            temptitles = set(map(lambda c:c[0], cands))

            if flag:
                titles = temptitles
                flag = False
            else:
                titles = titles & temptitles

        print("all terms searched") 
        return titles

    def sortSearch(self, terms):
        c = self.db.cursor()

        documentVectors = {}
        defaultVector = []
        for n, term in enumerate(terms):
            cands = c.execute("SELECT document_id FROM postings WHERE term=?", (term,)).fetchall()
            if cands == None or len(cands) ==  0:
                defaultVector.append(0)
                continue
            # non-zero div is ensured
            termPoint = (1 + math.log(len(cands)) * math.log(self.collection.num_documents() / len(cands)))
            defaultVector.append(termPoint)

            for cand in cands:
                if cand[0] in documentVectors:
                    documentVectors[cand[0]][n] = termPoint
                else:
                    documentVectors[cand[0]] = [0 for i in range(len(terms))]
                    documentVectors[cand[0]][n] = termPoint

        max_cos = -1
        best_title = ''

        for title, documentVector in documentVectors.items():
            cos = numpy.dot(documentVector, defaultVector) / (numpy.linalg.norm(documentVector) * numpy.linalg.norm(defaultVector))
            if max_cos < cos:
                max_cos = cos
                best_title = title
        return best_title

    def ngrams_search(self, ngrams):
        c = self.db.cursor()
        is_first = True
        for term in ngrams:
            cands = c.execute("SELECT document_id FROM postings WHERE term=?", (term,)).fetchall()
            if len(cands) == 0: continue

            temptitles = set(map(lambda c:c[0], cands))
            if is_first:
                titles = temptitles
                is_first = False
            else:
                titles = titles & temptitles
            return titles

    def sortSearchReturnTable(self, terms):
        c = self.db.cursor()

        documentVectors = {}
        defaultVector = []
        for n, term in enumerate(terms):
            cands = c.execute("SELECT document_id FROM postings WHERE term=?", (term,)).fetchall()
            if cands == None or len(cands) == 0:
                defaultVector.append(0)
                continue
            # non-zero div is ensured
            termPoint = (1 + math.log(len(cands)) * math.log(self.collection.num_documents() / len(cands)))
            defaultVector.append(termPoint)

            for cand in cands:
                if cand[0] in documentVectors:
                    documentVectors[cand[0]][n] = termPoint
                else:
                    documentVectors[cand[0]] = [0 for i in range(len(terms))]
                    documentVectors[cand[0]][n] = termPoint

        max_cos = -1
        best_title = ''

        table = {}
        for title, documentVector in documentVectors.items():
            cos = numpy.dot(documentVector, defaultVector) / (numpy.linalg.norm(documentVector) * numpy.linalg.norm(defaultVector))
            table[title] = cos

        return table
    
    def returnBestFromTable(self, table):

        max_title = ''
        max_val = -1
        for title in table.keys():
            if max_val < table[title]:
                max_val = table[title]
                max_title = title

        return max_title

    def mergeTable(self, table1, table2):
        # table1 < tabl2 is pereferable
        
        returnTable = {}

        for title in table1.keys():
            if title in table2:
                returnTable[title] = table1[title] + table2[title] * 0.5
            else:
                returnTable[title] = table1[title]

        return returnTable

    def generate(self):
        # indexing process
        c = self.db.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS postings (
            term TEXT NOT NULL,
            document_id TEXT NOT NULL,
            times INTEGER
        );""")
        parser = natto.MeCab()
        articles = self.collection.get_all_documents()
        for article in articles:

            dict = {}
            for node in parser.parse(article.text(), as_nodes=True):
                if node.is_nor():
                    features = node.feature.split(',')
                    term = features[6] if len(features) == 9 else node.surface
                    if FilterWords.shouldBeIncluded(features):
                        if term in dict:
                            dict[term] += 1
                        else:
                            dict[term] = 1
            for term in dict.keys():
                c.execute("INSERT INTO postings VALUES(?, ?, ?)", (term, article.id(), dict[term],))

        c.execute("""CREATE INDEX IF NOT EXISTS termindexs ON postings(term, document_id);""")
        self.db.commit()

    def generateFromOpeningText(self):
        # indexing process
        c = self.db.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS postings (
            term TEXT NOT NULL,
            document_id TEXT NOT NULL,
            times INTEGER
        );""")
        parser = natto.MeCab()
        articles = self.collection.get_all_documents()
        count = 0
        for article in articles:
            count += 1
            if count > 100:
                break

            dict = {}
            for node in parser.parse(article.opening_text, as_nodes=True):
                if node.is_nor():
                    features = node.feature.split(',')
                    term = features[6] if len(features) == 9 else node.surface
                    if FilterWords.shouldBeIncluded(features):
                        if term in dict:
                            dict[term] += 1
                        else:
                            dict[term] = 1
            for term in dict.keys():
                c.execute("INSERT INTO postings VALUES(?, ?, ?)", (term, article.id(), dict[term],))

        c.execute("""CREATE INDEX IF NOT EXISTS termindexs ON postings(term, document_id);""")
        self.db.commit()
    
    def generate_ngrams(self):
        c = self.db.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS ngrams (
            term TEXT NOT NULL,
            document_id TEXT NOT NULL
        );""")
        articles = self.collection.get_all_documents()
        count = 0
        analyse = AnalyseQuery()

        for article in articles:
            count += 1
            if count > 100: break

            ngrams = analyse.divide_ngrams(article.text())
            ngrams_titles = [(ngram, article.id()) for ngram in ngrams]
            c.executemany("INSERT INTO ngrams(term, document_id) VALUES(?, ?)", ngrams_titles)


        c.execute("""CREATE INDEX IF NOT EXISTS termindexs ON ngrams(term, document_id);""")
        self.db.commit()



class WikipediaCollection(Collection):
    """A collection of WikipediaArticles.
    """
    def __init__(self, filename):
        self._cached_num_documents = None
        self.db = sqlite3.connect(filename)

    def find_article_by_title(self, query):
        """Finds an article with a title matching the query.
        
        Returns:
            WikipediaArticle: Returns matching WikipediaArticle.
        """
        c = self.db.cursor()
        row = c.execute("SELECT title, text, opening_text, auxiliary_text, categories, headings, wiki_text, popularity_score, num_incoming_links FROM articles WHERE title=?", (query,)).fetchone()
        if row is None:
            return None
        return WikipediaArticle(self,
            row[0], # title
            row[1], # text
            row[2], # opening_text
            json.loads(row[3]), # auxiliary_text
            json.loads(row[4]), # categories
            json.loads(row[5]), # headings
            row[6], # wiki_text
            row[7], # popularity_score
            row[8], # num_incoming_links
        )

    def get_document_by_id(self, doc_id):
        """Gets the document (i.e. WikipediaArticle) for the given id (i.e. title).

        Override for Collection.
        
        Returns:
            WikipediaArticle: The WikipediaArticle for the given id.
        """
        c = self.db.cursor()
        row = c.execute("SELECT text, opening_text, auxiliary_text, categories, headings, wiki_text, popularity_score, num_incoming_links FROM articles WHERE title=?", (doc_id,)).fetchone()
        if row is None:
            return None
        return WikipediaArticle(self, doc_id,
            row[0], # text
            row[1], # opening_text
            json.loads(row[2]), # auxiliary_text
            json.loads(row[3]), # categories
            json.loads(row[4]), # headings
            row[5], # wiki_text
            row[6], # popularity_score
            row[7], # num_incoming_links
        )

    def num_documents(self):
        """Returns the number of documents (i.e. WikipediaArticle).

        Override for Collection.
        
        Returns:
            int: The number of documents in the collection.
        """
        if self._cached_num_documents is None:
            c = self.db.cursor()
            num_documents = c.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
            self._cached_num_documents = num_documents
        return self._cached_num_documents

    def get_all_documents(self):
        """Creates an iterator that iterates through all documents (i.e. WikipediaArticles) in the collection.
        
        Returns:
            Iterable[WikipediaArticle]: All the documents in the collection.
        """
        c = self.db.cursor()
        c.execute("SELECT title, text, opening_text, auxiliary_text, categories, headings, wiki_text, popularity_score, num_incoming_links FROM articles")
        BLOCK_SIZE = 1000
        while True:
            block = c.fetchmany(BLOCK_SIZE)
            if len(block) == 0:
                break
            for row in block:
                yield WikipediaArticle(self,
                    row[0], # title
                    row[1], # text
                    row[2], # opening_text
                    json.loads(row[3]), # auxiliary_text
                    json.loads(row[4]), # categories
                    json.loads(row[5]), # headings
                    row[6], # wiki_text
                    row[7], # popularity_score
                    row[8], # num_incoming_links
		)

