import os
import wp

try:
	os.remove("./data/index3.db")
except OSError:
	pass

collection = wp.WikipediaCollection("./data/wp.db")
index = wp.Index("./data/index4.db", collection)
index.generate()
index.generate_ngrams()
index.generateFromOpeningText()
