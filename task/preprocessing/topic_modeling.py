import time
from nltk.corpus import stopwords as stop_words

from contextualized_topic_models.models.ctm import CombinedTM
from contextualized_topic_models.utils.data_preparation import TopicModelDataPreparation
from contextualized_topic_models.utils.preprocessing import WhiteSpacePreprocessingStopwords as sp

def topic_(args):

    start_time = time.time()

    #===================================#
    #==============Logging==============#
    #===================================#

    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    handler = TqdmLoggingHandler()
    handler.setFormatter(logging.Formatter(" %(asctime)s - %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
    logger.propagate = False

    #===================================#
    #=============Data Load=============#
    #===================================#

    write_log(logger, 'Start preprocessing!')

    nltk.download('stopwords')
    stopwords = list(stop_words.words("english"))

    src_list, trg_list = total_data_load(args)

    #===================================#
    #==========Topic Modeling===========#
    #===================================#

    sp_train_out = sp(src_list['train'], stopwords_list=stopwords).preprocess()
    sp_valid_out = sp(src_list['valid'], stopwords_list=stopwords).preprocess()
    sp_test_out = sp(src_list['test'], stopwords_list=stopwords).preprocess()

    qt = TopicModelDataPreparation("all-mpnet-base-v2")
    training_dataset = qt.fit(text_for_contextual=sp_train_out[0], text_for_bow=sp_train_out[1])

    ctm = CombinedTM(bow_size=len(qt.vocab), contextual_size=768, n_components=50) # 50 topics
    ctm.fit(training_dataset) # run the model

    ctm.get_topics(2)