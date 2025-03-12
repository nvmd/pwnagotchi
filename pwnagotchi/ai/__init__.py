import os
import time
import logging
import sys

logger = logging.getLogger(__name__)

# https://stackoverflow.com/questions/40426502/is-there-a-way-to-suppress-the-messages-tensorflow-prints/40426709
# os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'  # or any {'0', '1', '2'}


def load(config, agent, epoch, from_disk=True):
    config = config['ai']

    begin = time.time()

    logger.info("bootstrapping dependencies ...")

    start = time.time()
    SB_BACKEND = "stable_baselines3"

    from stable_baselines3 import A2C
    logger.debug("A2C imported in %.2fs" % (time.time() - start))

    # remove invalid ai.parameters leftover from tensor_flow, if present
    for key in [ 'alpha', 'epsilon', 'lr_schedule' ]:
        if key in config['params']:
            logger.info("Removing legacy ai parameter %s" % key);
            del config['params'][key]
    
    start = time.time()
    from stable_baselines3.a2c import MlpPolicy
    logger.debug("MlpPolicy imported in %.2fs" % (time.time() - start))
    SB_A2C_POLICY = MlpPolicy

    start = time.time()
    from stable_baselines3.common.vec_env import DummyVecEnv
    logger.debug("DummyVecEnv imported in %.2fs" % (time.time() - start))

    start = time.time()
    import pwnagotchi.ai.gym as wrappers
    logger.debug("gym wrapper imported in %.2fs" % (time.time() - start))

    env = wrappers.Environment(agent, epoch)
    env = DummyVecEnv([lambda: env])

    logger.info("creating model ...")

    start = time.time()
    a2c = A2C(SB_A2C_POLICY, env, **config['params'])
    logger.debug("A2C created in %.2fs" % (time.time() - start))

    if from_disk and os.path.exists(config['path']):
        logger.info("loading model from %s ..." % config['path'])
        start = time.time()
        a2c.load(config['path'], env)
        logger.debug("A2C loaded in %.2fs" % (time.time() - start))
    else:
        logger.info("model created:")
        for key, value in config['params'].items():
            logger.info("      %s: %s" % (key, value))

    logger.debug("total loading time is %.2fs" % (time.time() - begin))

    return a2c