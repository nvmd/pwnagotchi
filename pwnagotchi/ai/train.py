# import _thread
import threading
import time
import random
import os
import json
import logging

import pwnagotchi.plugins as plugins
import pwnagotchi.ai as ai

logger = logging.getLogger(__name__)

class Stats(object):
    def __init__(self, path, events_receiver):
        self._lock = threading.Lock()
        self._receiver = events_receiver

        self.path = path
        self.born_at = time.time()
        # total epochs lived (trained + just eval)
        self.epochs_lived = 0
        # total training epochs
        self.epochs_trained = 0

        self.worst_reward = 0.0
        self.best_reward = 0.0

        self.load()

    def on_epoch(self, data, training):
        best_r = False
        worst_r = False
        with self._lock:
            reward = data['reward']
            if reward < self.worst_reward:
                self.worst_reward = reward
                worst_r = True

            elif reward > self.best_reward:
                best_r = True
                self.best_reward = reward

            self.epochs_lived += 1
            if training:
                self.epochs_trained += 1

        self.save()

        if best_r:
            self._receiver.on_ai_best_reward(reward)
        elif worst_r:
            self._receiver.on_ai_worst_reward(reward)

    def load(self):
        with self._lock:
            if os.path.exists(self.path) and os.path.getsize(self.path) > 0:
                logger.info("loading stats from %s" % self.path)
                with open(self.path, 'rt') as fp:
                    obj = json.load(fp)

                self.born_at = obj['born_at']
                self.epochs_lived, self.epochs_trained = obj['epochs_lived'], obj['epochs_trained']
                self.best_reward, self.worst_reward = obj['rewards']['best'], obj['rewards']['worst']

    def save(self):
        with self._lock:
            logger.info("saving stats to %s" % self.path)

            data = json.dumps({
                'born_at': self.born_at,
                'epochs_lived': self.epochs_lived,
                'epochs_trained': self.epochs_trained,
                'rewards': {
                    'best': self.best_reward,
                    'worst': self.worst_reward
                }
            })

            temp = "%s.tmp" % self.path
            back = "%s.bak" % self.path
            with open(temp, 'wt') as fp:
                fp.write(data)

            if os.path.isfile(self.path):
                os.replace(self.path, back)
            os.replace(temp, self.path)


class AsyncTrainer(object):
    def __init__(self, config):
        self._config = config
        self._model = None
        self._is_training = False
        self._training_epochs = 0
        self._nn_path = self._config['ai']['path']
        self._stats = Stats("%s.json" % os.path.splitext(self._nn_path)[0], self)

    def set_training(self, training, for_epochs=0):
        self._is_training = training
        self._training_epochs = for_epochs

        if training:
            self.on_ai_training_start(for_epochs)
        else:
            self.on_ai_training_end()

    def is_training(self):
        return self._is_training

    def training_epochs(self):
        return self._training_epochs

    def start_ai(self):
        #_thread.start_new_thread(self._ai_worker, ())
        threading.Thread(target=self._ai_worker, args=(), name="AI Worker", daemon=True).start()

    def _save_ai(self):
        logger.info("saving model to %s ..." % self._nn_path)
        temp = "%s.tmp" % self._nn_path
        self._model.save(temp)
        os.replace(temp, self._nn_path)

    def on_ai_step(self):
        self._model.env.render()

        if self._is_training:
            self._save_ai()

        self._stats.on_epoch(self._epoch.data(), self._is_training)

    def on_ai_policy(self, new_params):
        self.set_policy(new_params)
        plugins.on('ai_policy', self, new_params)

    def on_ai_ready(self):
        self._view.on_ai_ready()
        plugins.on('ai_ready', self)

    def on_ai_best_reward(self, r):
        logger.info("best reward so far: %s" % r)
        self._view.on_motivated(r)
        plugins.on('ai_best_reward', self, r)

    def on_ai_worst_reward(self, r):
        logger.info("worst reward so far: %s" % r)
        self._view.on_demotivated(r)
        plugins.on('ai_worst_reward', self, r)

    def on_ai_training_start(self, for_epochs):
        logger.warning("training for %d epochs ..." % for_epochs)
        self._view.set("mode", " AI*")
        plugins.on('ai_training_start', self, for_epochs)

    def on_ai_training_step(self, _locals, _globals):
        self._model.env.render()
        plugins.on('ai_training_step', self, _locals, _globals)
        # Functional callbacks are converted into ConvertCallback internally
        # With the function being treated as an "_on_step" callback
        # * called by the model after each call to `env.step()`
        # * training will abort early if callback returns False
        return True

    def on_ai_training_end(self):
        self._view.set("mode", "  AI")
        plugins.on('ai_training_end', self)

    def _ai_worker(self):
        try:
            self._model = ai.load(self._config, self, self._epoch)
            epochs_per_episode = self._config['ai']['epochs_per_episode']

            self.on_ai_ready()

            obs = None
            while True:
                try:
                    self._model.env.render()
                    # enter in training mode?
                    if random.random() > self._config['ai']['laziness']:
                        try:
                            self.set_training(True, epochs_per_episode)
                            # back up brain file before starting new training set
                            if os.path.isfile(self._nn_path):
                                back = "%s.bak" % self._nn_path
                                os.replace(self._nn_path, back)

                            start = time.time()
                            self._model.learn(total_timesteps=epochs_per_episode,
                                              callback=self.on_ai_training_step)
                            logger.info("learning episode took %.2fs" % (time.time() - start))
                        except Exception as e:
                            logger.exception("error while training (%s)", e)
                        finally:
                            self.set_training(False)

                            # Environment is wrapped in a DummyVecEnv
                            # stable-baselines3 DummyVecEnv's reset() returns only observation
                            # https://stable-baselines3.readthedocs.io/en/master/guide/vec_envs.html#vecenv-api-vs-gym-api
                            obs = self._model.env.reset()
                    # init the first time
                    elif obs is None:
                        obs = self._model.env.reset()

                    # run the inference
                    start = time.time()
                    action, _ = self._model.predict(obs)
                    logger.info("inference took %.2fs" % (time.time() - start))

                    # save the observation for the next inference
                    # one return value less than with gym api
                    # https://stable-baselines3.readthedocs.io/en/master/guide/vec_envs.html#vecenv-api-vs-gym-api
                    obs, _, _, _ = self._model.env.step(action)
                except Exception as e:
                    logger.exception(f"ignoring exception: {e}")
                    continue
        except Exception as e:
            logger.exception(f"Error while starting AI: {e}")
            logger.info("Deleting brain and restarting.")
            os.system(f"rm {self._nn_path}")
            # rely on systemd to restart us according to restart policy
            logger.critical("Exiting to be restarted...")
            os._exit(2) # kill all threads
